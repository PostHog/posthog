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
    // The event of every step on the path, optional steps included, in step order. Only the replay slots read it.
    // `uuids` keeps the required steps only, because the duplicate-event check reads it and an optional step must
    // not change which paths count.
    #[serde(default)]
    pub step_uuids: Vec<Uuid>,
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

pub const DEFAULT_ENTERED_TIMESTAMP: EnteredTimestamp = EnteredTimestamp {
    timestamp: 0.0,
    excluded: false,
    timings: vec![],
    uuids: vec![],
    steps: 0,
    step_uuids: vec![],
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

        args.prop_vals
            .iter()
            .for_each(|prop_val| self.loop_prop_val(args, prop_val));

        &self.results
    }

    #[inline(always)]
    fn loop_prop_val(&mut self, args: &Args, prop_val: &PropVal) {
        let mut vars = Vars {
            max_step: (0, DEFAULT_ENTERED_TIMESTAMP.clone()),
            event_uuids: repeat(Vec::new()).take(args.num_steps).collect(),
            entered_timestamp: vec![DEFAULT_ENTERED_TIMESTAMP.clone(); args.num_steps + 1],
        };

        let filtered_events = args
            .value
            .iter()
            .filter(|e| {
                if args.breakdown_attribution_type == "all_events" {
                    e.breakdown == *prop_val
                } else {
                    true
                }
            })
            .chunk_by(|e| e.timestamp);

        for (timestamp, events_with_same_timestamp) in &filtered_events {
            let events_with_same_timestamp: Vec<_> = events_with_same_timestamp.collect();
            vars.entered_timestamp[0] = EnteredTimestamp {
                timestamp,
                excluded: false,
                timings: vec![],
                uuids: vec![],
                steps: 0,
                step_uuids: vec![],
            };

            if events_with_same_timestamp.len() == 1 {
                self.process_event(
                    args,
                    &mut vars,
                    events_with_same_timestamp[0],
                    prop_val,
                    false,
                );
            } else if events_with_same_timestamp
                .iter()
                .map(|x| &x.steps)
                .all_equal()
            {
                // Deal with the most common case where they are all the same event (order doesn't matter)
                for event in events_with_same_timestamp {
                    self.process_event(args, &mut vars, event, prop_val, false);
                }
            } else {
                // Handle permutations for different events with the same timestamp
                // We ignore strict steps and exclusions in this case
                // The behavior here is mostly dictated by how it was handled in the old style

                let sorted_events = events_with_same_timestamp
                    .iter()
                    .flat_map(|&event| {
                        event
                            .steps
                            .iter()
                            .filter(|&&step| step > 0)
                            .map(|&step| Event {
                                steps: vec![step],
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

        let matched_steps = (0..final_index).filter(|i| final_value.steps & (1 << i) != 0);
        for (step_index, uuid) in matched_steps.zip(&final_value.step_uuids) {
            // Always put the actual event uuids first, we use it to extract timestamps
            // This might create duplicates, but that's fine (we can remove it in clickhouse)
            vars.event_uuids[step_index].insert(0, *uuid);
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
                        let mut s = previous_step.step_uuids.clone();
                        s.push(event.uuid);
                        let new_entered_timestamp = EnteredTimestamp {
                            timestamp: previous_step.timestamp,
                            excluded: previous_step.excluded,
                            timings: t,
                            uuids: u,
                            steps: previous_step.steps | (1 << (step - 1)),
                            step_uuids: s,
                        };

                        if !previous_step.excluded {
                            vars.entered_timestamp[step] = new_entered_timestamp.clone();
                            if vars.event_uuids[step - 1].len() < MAX_REPLAY_EVENTS - 1 {
                                vars.event_uuids[step - 1].push(event.uuid);
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
    use rstest::rstest;

    #[rstest]
    #[case(vec![1, 4])]
    #[case(vec![1, 2, 4])]
    #[case(vec![1, 2, 3, 4])]
    fn matched_events_keep_their_funnel_step(#[case] visited_steps: Vec<i8>) {
        let args = Args {
            num_steps: 5,
            conversion_window_limit: 3600,
            breakdown_attribution_type: "first_touch".to_string(),
            funnel_order_type: "ordered".to_string(),
            prop_vals: vec![PropVal::Int(0)],
            optional_steps: vec![2, 3],
            value: visited_steps
                .iter()
                .map(|&step| Event {
                    timestamp: f64::from(step),
                    uuid: Uuid::from_u128(step as u128),
                    breakdown: PropVal::Int(0),
                    steps: vec![step],
                })
                .collect(),
        };

        let results = run(&args);
        assert_eq!(results.len(), 1);
        let result = &results[0];
        assert_eq!(result.0, 1);
        assert_eq!(result.2, vec![3.0]);
        for step in 1..=args.num_steps {
            if visited_steps.contains(&(step as i8)) {
                assert_eq!(result.3[step - 1][0], Uuid::from_u128(step as u128));
                assert!(result.3[step - 1]
                    .iter()
                    .all(|uuid| *uuid == Uuid::from_u128(step as u128)));
            } else {
                assert!(result.3[step - 1].is_empty());
            }
        }
    }

    #[test]
    fn optional_step_starts_with_the_event_from_the_selected_path() {
        let args = Args {
            num_steps: 3,
            conversion_window_limit: 3600,
            breakdown_attribution_type: "first_touch".to_string(),
            funnel_order_type: "ordered".to_string(),
            prop_vals: vec![PropVal::Int(0)],
            optional_steps: vec![2],
            value: [1, 2, 1, 2, 3]
                .iter()
                .enumerate()
                .map(|(index, &step)| Event {
                    timestamp: (index + 1) as f64,
                    uuid: Uuid::from_u128((index + 1) as u128),
                    breakdown: PropVal::Int(0),
                    steps: vec![step],
                })
                .collect(),
        };

        let results = run(&args);
        assert_eq!(results[0].2, vec![2.0]);
        for (step, uuid) in [3, 4, 5].iter().enumerate() {
            assert_eq!(results[0].3[step][0], Uuid::from_u128(*uuid));
        }
    }

    // Each event is (timestamp, uuid, steps). The expected counts are the ones the previous UDF version returns.
    #[rstest]
    #[case::optional_and_next_required(
        3,
        vec![2],
        vec![(1.0, 1, vec![1]), (2.0, 2, vec![2, 3]), (2.0, 3, vec![1])],
        1,
        0b111,
        vec![3, 2, 2]
    )]
    #[case::two_optionals_and_next_required(
        4,
        vec![2, 3],
        vec![(1.0, 1, vec![1]), (2.0, 2, vec![2, 3, 4]), (2.0, 3, vec![1])],
        1,
        0b1111,
        vec![3, 2, 2, 2]
    )]
    #[case::optional_and_later_required(
        4,
        vec![2],
        vec![(1.0, 1, vec![1]), (2.0, 10, vec![2, 4]), (2.0, 11, vec![3])],
        2,
        0b1111,
        vec![1, 10, 11, 10]
    )]
    fn optional_step_matches_do_not_change_counts(
        #[case] num_steps: usize,
        #[case] optional_steps: Vec<i8>,
        #[case] events: Vec<(f64, u128, Vec<i8>)>,
        #[case] step_reached: i8,
        #[case] steps_bitfield: u32,
        #[case] first_event_per_step: Vec<u128>,
        #[values("ordered", "strict")] funnel_order_type: &str,
    ) {
        let args = Args {
            num_steps,
            conversion_window_limit: 3600,
            breakdown_attribution_type: "first_touch".to_string(),
            funnel_order_type: funnel_order_type.to_string(),
            prop_vals: vec![PropVal::Int(0)],
            optional_steps,
            value: events
                .into_iter()
                .map(|(timestamp, uuid, steps)| Event {
                    timestamp,
                    uuid: Uuid::from_u128(uuid),
                    breakdown: PropVal::Int(0),
                    steps,
                })
                .collect(),
        };

        let results = run(&args);
        assert_eq!(results[0].0, step_reached);
        assert_eq!(results[0].4, steps_bitfield);
        for (step, uuid) in first_event_per_step.iter().enumerate() {
            assert_eq!(results[0].3[step][0], Uuid::from_u128(*uuid));
        }
    }
}
