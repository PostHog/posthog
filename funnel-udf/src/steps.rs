use crate::parsing::u64_or_string;
use crate::types::PropVal;
use crate::unordered_steps::AggregateFunnelRowUnordered;
use itertools::Itertools;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::iter::repeat;
use uuid::Uuid;

#[derive(Clone, Deserialize)]
pub struct EnteredTimestamp {
    pub timestamp: f64,
    pub excluded: bool,
    pub timings: Vec<f64>,
    pub uuids: Vec<Uuid>,
    pub steps: u32,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Event {
    pub timestamp: f64,
    pub uuid: Uuid,
    pub breakdown: PropVal,
    pub steps: Vec<i8>,
}

#[derive(Deserialize, Debug)]
pub struct Args {
    pub num_steps: usize,
    #[serde(deserialize_with = "u64_or_string")]
    pub conversion_window_limit: u64, // In seconds
    pub breakdown_attribution_type: String,
    pub funnel_order_type: String,
    pub prop_vals: Vec<PropVal>,
    pub optional_steps: Vec<i8>,
    pub value: Vec<Event>,
}

#[derive(Serialize)]
pub struct Result(
    pub i8,
    pub PropVal,
    pub Vec<f64>,
    pub Vec<Vec<Uuid>>,
    pub u32,
);

struct Vars {
    // The furthest step we've made it to, 1 indexed
    max_step: (usize, EnteredTimestamp),
    event_uuids: Vec<Vec<Uuid>>,
    entered_timestamp: Vec<EnteredTimestamp>,
}

struct AggregateFunnelRow {
    breakdown_step: Option<usize>,
    results: Vec<Result>,
}

const MAX_REPLAY_EVENTS: usize = 10;

// Two consecutive steps often fire from independent scripts on one page load, a few
// milliseconds apart rather than at the exact same microsecond. We treat events within
// this window as simultaneous so they take the order-independent permutation path, the
// same path exact ties already take. Without it, the arrival race decides whether the
// funnel counts the conversion. The window is far below any real conversion window (the
// smallest is an hour), so it cannot practically flip a conversion-window decision.
const SIMULTANEITY_WINDOW_SECONDS: f64 = 0.05;

// The permutation path drops exclusion steps and skips the strict-sequence reset. That is
// safe for exact ties, which are genuinely simultaneous, but widening the window would pull
// exclusion events and strict-funnel neighbors into that lossy path and silently over-count.
// So strict funnels and funnels that use exclusions keep exact-tie grouping (window 0.0),
// which matches the previous behavior exactly.
fn simultaneity_window(args: &Args) -> f64 {
    let has_exclusions = args.value.iter().any(|e| e.steps.iter().any(|&s| s < 0));
    if args.funnel_order_type == "strict" || has_exclusions {
        0.0
    } else {
        SIMULTANEITY_WINDOW_SECONDS
    }
}

// Group consecutive events that fall within `window` of the group's first event. Events
// arrive sorted by timestamp ascending, so each group is bounded to one window and a long
// run of closely-spaced events cannot collapse into one group. With window 0.0 this groups
// only exact ties. Groups are yielded lazily: a caller that reaches its goal stops pulling,
// so the rest of the events are never scanned or allocated, and only the current group is
// held at a time.
fn group_simultaneous<'a>(
    events: impl Iterator<Item = &'a Event>,
    window: f64,
) -> impl Iterator<Item = Vec<&'a Event>> {
    let mut events = events.peekable();
    std::iter::from_fn(move || {
        let first = events.next()?;
        let group_start = first.timestamp;
        let mut group = vec![first];
        while let Some(&next) = events.peek() {
            if next.timestamp - group_start > window {
                break;
            }
            group.push(next);
            events.next();
        }
        Some(group)
    })
}

pub const DEFAULT_ENTERED_TIMESTAMP: EnteredTimestamp = EnteredTimestamp {
    timestamp: 0.0,
    excluded: false,
    timings: vec![],
    uuids: vec![],
    steps: 0,
};

pub fn run(args: &Args) -> Vec<Result> {
    if args.funnel_order_type == "unordered" {
        let mut row = AggregateFunnelRowUnordered {
            results: Vec::with_capacity(args.prop_vals.len()),
            breakdown_step: Option::None,
        };
        row.calculate_funnel_from_user_events(args);
        return row.results;
    }
    let mut row = AggregateFunnelRow {
        results: Vec::with_capacity(args.prop_vals.len()),
        breakdown_step: Option::None,
    };
    row.calculate_funnel_from_user_events(args);
    row.results
}

pub fn process_line(line: &str) -> Value {
    match parse_args(line) {
        Ok(args) => json!({ "result": run(&args) }),
        Err(e) => {
            eprintln!(
                "funnels error: invalid JSON input while parsing steps Args: {e}. Input: {line}"
            );
            json!({ "error": format!("invalid JSON input: {e}") })
        }
    }
}

#[inline(always)]
fn parse_args(line: &str) -> std::result::Result<Args, serde_json::Error> {
    serde_json::from_str(line)
}

impl AggregateFunnelRow {
    #[inline(always)]
    fn calculate_funnel_from_user_events(&mut self, args: &Args) -> &Vec<Result> {
        if args.breakdown_attribution_type.starts_with("step_") {
            self.breakdown_step = args.breakdown_attribution_type[5..].parse::<usize>().ok()
        }

        let window = simultaneity_window(args);
        args.prop_vals
            .iter()
            .for_each(|prop_val| self.loop_prop_val(args, prop_val, window));

        &self.results
    }

    #[inline(always)]
    fn loop_prop_val(&mut self, args: &Args, prop_val: &PropVal, window: f64) {
        let mut vars = Vars {
            max_step: (0, DEFAULT_ENTERED_TIMESTAMP.clone()),
            event_uuids: repeat(Vec::new()).take(args.num_steps).collect(),
            entered_timestamp: vec![DEFAULT_ENTERED_TIMESTAMP.clone(); args.num_steps + 1],
        };

        let simultaneous_groups = group_simultaneous(
            args.value.iter().filter(|e| {
                if args.breakdown_attribution_type == "all_events" {
                    e.breakdown == *prop_val
                } else {
                    true
                }
            }),
            window,
        );

        for simultaneous_events in simultaneous_groups {
            vars.entered_timestamp[0] = EnteredTimestamp {
                timestamp: simultaneous_events[0].timestamp,
                excluded: false,
                timings: vec![],
                uuids: vec![],
                steps: 0,
            };

            if simultaneous_events.len() == 1 {
                self.process_event(args, &mut vars, simultaneous_events[0], prop_val, false);
            } else if simultaneous_events.iter().map(|x| &x.steps).all_equal() {
                // Deal with the most common case where they are all the same event (order doesn't matter)
                for event in simultaneous_events {
                    self.process_event(args, &mut vars, event, prop_val, false);
                }
            } else {
                // Handle permutations for different events that fired near-simultaneously
                // We ignore strict steps and exclusions in this case
                // The behavior here is mostly dictated by how it was handled in the old style

                // Treat every event in the group as firing at the group's first timestamp,
                // so a reordered pair reports a 0 ms gap instead of a negative conversion time.
                let group_timestamp = simultaneous_events[0].timestamp;
                let sorted_events = simultaneous_events
                    .iter()
                    .flat_map(|&event| {
                        event
                            .steps
                            .iter()
                            .filter(|&&step| step > 0)
                            .map(|&step| Event {
                                steps: vec![step],
                                timestamp: group_timestamp,
                                ..event.clone()
                            })
                    })
                    .sorted_by_key(|event| event.steps[0]);

                // Run exclusions, if they exist, then run matching events.
                for event in sorted_events {
                    self.process_event(args, &mut vars, &event, prop_val, true);
                }
            }

            // If we hit the goal, we can terminate early
            if vars.entered_timestamp[args.num_steps].timestamp > 0.0 {
                break;
            }
        }

        // Find the furthest step we have made it to and print it
        let final_index = vars.max_step.0;
        let final_value = &vars.max_step.1;

        if final_value.excluded {
            self.results
                .push(Result(-1, prop_val.clone(), vec![], vec![], 0));
            return;
        }

        let optional_count = args
            .optional_steps
            .iter()
            .filter(|i| **i <= final_index as i8)
            .count();

        for i in 0..(final_index - optional_count) {
            //if event_uuids[i].len() >= MAX_REPLAY_EVENTS && !event_uuids[i].contains(&final_value.uuids[i]) {
            // Always put the actual event uuids first, we use it to extract timestamps
            // This might create duplicates, but that's fine (we can remove it in clickhouse)
            vars.event_uuids[i].insert(0, final_value.uuids[i].clone());
        }

        self.results.push(Result(
            (final_index - 1 - optional_count) as i8,
            prop_val.clone(),
            final_value
                .timings
                .windows(2)
                .map(|w| w[1] - w[0])
                .collect(),
            vars.event_uuids,
            final_value.steps,
        ))
    }

    #[inline(always)]
    fn process_event(
        &mut self,
        args: &Args,
        vars: &mut Vars,
        event: &Event,
        prop_val: &PropVal,
        processing_multiple_events: bool,
    ) {
        for step in event.steps.iter().rev() {
            let mut exclusion = false;
            let step = (if *step < 0 {
                exclusion = true;
                -*step
            } else {
                *step
            }) as usize;

            // Find the closest previous step that has a timestamp (either the direct previous or an earlier optional step)
            let mut previous_step_index = step - 1;

            // First, find the matching previous step
            let mut previous_timestamp = vars.entered_timestamp[previous_step_index].timestamp;
            let mut in_match_window = previous_timestamp != 0.0
                && event.timestamp - previous_timestamp <= args.conversion_window_limit as f64;

            // Go backwards until you hit a match or you get to the previous mandatory step
            while previous_step_index > 0
                && (previous_timestamp == 0.0 || !in_match_window)
                && args.optional_steps.contains(&(previous_step_index as i8))
            {
                previous_step_index -= 1;
                previous_timestamp = vars.entered_timestamp[previous_step_index].timestamp;
                in_match_window = previous_timestamp != 0.0
                    && event.timestamp - previous_timestamp <= args.conversion_window_limit as f64;
            }

            let already_reached_this_step = vars.entered_timestamp[step].timestamp
                == previous_timestamp
                && vars.entered_timestamp[step].timestamp != 0.0;

            if in_match_window && !already_reached_this_step {
                let previous_step = &vars.entered_timestamp[previous_step_index];

                if exclusion {
                    if !previous_step.excluded {
                        vars.entered_timestamp[previous_step_index].excluded = true;
                        if vars.max_step.0 == previous_step_index {
                            let max_timestamp_in_match_window = (event.timestamp
                                - vars.max_step.1.timestamp)
                                <= args.conversion_window_limit as f64;
                            if max_timestamp_in_match_window {
                                vars.max_step.1.excluded = true;
                            }
                        }
                    }
                } else {
                    let is_unmatched_step_attribution = self
                        .breakdown_step
                        .map(|breakdown_step| previous_step_index == breakdown_step)
                        .unwrap_or(false)
                        && *prop_val != event.breakdown;
                    let already_used_event =
                        processing_multiple_events && previous_step.uuids.contains(&event.uuid);

                    if !is_unmatched_step_attribution && !already_used_event {
                        let mut t = previous_step.timings.clone();
                        let mut u = previous_step.uuids.clone();
                        if !args.optional_steps.contains(&(step as i8)) {
                            t.push(event.timestamp);
                            u.push(event.uuid);
                        }
                        let new_entered_timestamp = EnteredTimestamp {
                            timestamp: previous_step.timestamp,
                            excluded: previous_step.excluded,
                            timings: t,
                            uuids: u,
                            steps: previous_step.steps | (1 << (step - 1)),
                        };

                        if !previous_step.excluded {
                            vars.entered_timestamp[step] = new_entered_timestamp.clone();
                            if vars.event_uuids[previous_step_index].len() < MAX_REPLAY_EVENTS - 1 {
                                vars.event_uuids[previous_step_index].push(event.uuid);
                            }
                        }

                        if step > vars.max_step.0
                            || (step == vars.max_step.0 && vars.max_step.1.excluded)
                        {
                            vars.max_step = (step, new_entered_timestamp);
                        }
                    }
                }
            }
        }

        // If a strict funnel, clear all of the steps that we didn't match to
        // If we are processing multiple events, skip this step, because ordering makes it complicated
        if !processing_multiple_events && args.funnel_order_type == "strict" {
            for i in 1..vars.entered_timestamp.len() {
                if !event.steps.contains(&(i as i8)) {
                    vars.entered_timestamp[i] = DEFAULT_ENTERED_TIMESTAMP.clone();
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn run_events(events_json: &str) -> Vec<Result> {
        run_events_with_order("ordered", events_json)
    }

    fn run_events_with_order(order: &str, events_json: &str) -> Vec<Result> {
        let input = format!(
            r#"{{"num_steps":2,"conversion_window_limit":3600,"breakdown_attribution_type":"first_touch","funnel_order_type":"{order}","prop_vals":["en"],"optional_steps":[],"value":{events_json}}}"#
        );
        let args = parse_args(&input).unwrap();
        run(&args)
    }

    // step_reached is 0-indexed: 1 means both steps of a 2-step funnel matched.
    fn step_reached(events_json: &str) -> i8 {
        let results = run_events(events_json);
        assert_eq!(results.len(), 1);
        results[0].0
    }

    // Step 2 fires 10 ms before step 1 on the same page load. The arrival race must not
    // decide the conversion: both steps fall in one simultaneity window and match. The
    // reordered pair reports a 0 ms gap, never a negative conversion time.
    #[test]
    fn near_simultaneous_out_of_order_steps_convert() {
        let events = r#"[
            {"timestamp":1.00,"uuid":"00000000-0000-0000-0000-000000000002","breakdown":"en","steps":[2]},
            {"timestamp":1.01,"uuid":"00000000-0000-0000-0000-000000000001","breakdown":"en","steps":[1]}
        ]"#;
        let results = run_events(events);
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].0, 1);
        assert_eq!(results[0].2, vec![0.0]);
    }

    // Events further apart than the window keep their order, so an out-of-order step 2
    // before step 1 does not convert.
    #[test]
    fn steps_beyond_window_keep_ordering() {
        let events = r#"[
            {"timestamp":1.0,"uuid":"00000000-0000-0000-0000-000000000002","breakdown":"en","steps":[2]},
            {"timestamp":1.5,"uuid":"00000000-0000-0000-0000-000000000001","breakdown":"en","steps":[1]}
        ]"#;
        assert_eq!(step_reached(events), 0);
    }

    // A run of closely-spaced events cannot chain into one oversized group: each group is
    // bounded to one window from its first event.
    #[test]
    fn groups_are_bounded_to_one_window() {
        let e = |t: f64| Event {
            timestamp: t,
            uuid: Uuid::nil(),
            breakdown: PropVal::Int(0),
            steps: vec![1],
        };
        let events = vec![e(0.0), e(0.04), e(0.08), e(0.12)];
        let groups: Vec<_> =
            group_simultaneous(events.iter(), SIMULTANEITY_WINDOW_SECONDS).collect();
        assert_eq!(groups.len(), 2);
        assert_eq!(groups[0].len(), 2); // 0.00 and 0.04
        assert_eq!(groups[1].len(), 2); // 0.08 and 0.12
    }

    // A window of 0.0 groups only exact ties, so the helper stays equivalent to the
    // previous exact-timestamp grouping when tolerance is disabled.
    #[test]
    fn zero_window_groups_only_exact_ties() {
        let e = |t: f64| Event {
            timestamp: t,
            uuid: Uuid::nil(),
            breakdown: PropVal::Int(0),
            steps: vec![1],
        };
        let events = vec![e(1.0), e(1.0), e(1.01)];
        let groups: Vec<_> = group_simultaneous(events.iter(), 0.0).collect();
        assert_eq!(groups.len(), 2);
        assert_eq!(groups[0].len(), 2); // the two exact ties
        assert_eq!(groups[1].len(), 1);
    }

    // A funnel with an exclusion must keep exact-tie grouping. An exclusion event that
    // fires near a step must still exclude, not be dropped by the permutation path.
    #[test]
    fn near_simultaneous_exclusion_still_excludes() {
        // steps [-2] is an exclusion on step 2. It fires 10 ms after step 1, before step 2.
        let events = r#"[
            {"timestamp":1.00,"uuid":"00000000-0000-0000-0000-000000000001","breakdown":"en","steps":[1]},
            {"timestamp":1.01,"uuid":"00000000-0000-0000-0000-000000000009","breakdown":"en","steps":[-2]},
            {"timestamp":1.02,"uuid":"00000000-0000-0000-0000-000000000002","breakdown":"en","steps":[2]}
        ]"#;
        // -1 marks the row as excluded; the conversion is correctly rejected.
        assert_eq!(step_reached(events), -1);
    }

    // A strict funnel must keep exact-tie grouping. An unrelated event between two steps
    // still breaks the strict sequence.
    #[test]
    fn strict_funnel_breaks_on_near_simultaneous_unrelated_event() {
        // An event matching no step fires 10 ms after step 1, so strict step 2 cannot follow.
        let events = r#"[
            {"timestamp":1.00,"uuid":"00000000-0000-0000-0000-000000000001","breakdown":"en","steps":[1]},
            {"timestamp":1.01,"uuid":"00000000-0000-0000-0000-000000000009","breakdown":"en","steps":[]},
            {"timestamp":1.02,"uuid":"00000000-0000-0000-0000-000000000002","breakdown":"en","steps":[2]}
        ]"#;
        let results = run_events_with_order("strict", events);
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].0, 0);
    }
}
