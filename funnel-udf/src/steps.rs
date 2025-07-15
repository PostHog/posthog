use crate::unordered_steps::AggregateFunnelRowUnordered;
use crate::PropVal;
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

#[derive(Deserialize)]
pub struct Args {
    pub num_steps: usize,
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
};

pub fn process_line(line: &str) -> Value {
    let args = parse_args(line);
    if args.funnel_order_type == "unordered" {
        let mut aggregate_funnel_row = AggregateFunnelRowUnordered {
            results: Vec::with_capacity(args.prop_vals.len()),
            breakdown_step: Option::None,
        };
        let result = aggregate_funnel_row.calculate_funnel_from_user_events(&args);
        return json!({ "result": result });
    }
    let mut aggregate_funnel_row = AggregateFunnelRow {
        results: Vec::with_capacity(args.prop_vals.len()),
        breakdown_step: Option::None,
    };
    let result = aggregate_funnel_row.calculate_funnel_from_user_events(&args);
    json!({ "result": result })
}

#[inline(always)]
fn parse_args(line: &str) -> Args {
    serde_json::from_str(line).expect("Invalid JSON input")
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
            .group_by(|e| e.timestamp);

        for (timestamp, events_with_same_timestamp) in &filtered_events {
            let events_with_same_timestamp: Vec<_> = events_with_same_timestamp.collect();
            vars.entered_timestamp[0] = EnteredTimestamp {
                timestamp,
                excluded: false,
                timings: vec![],
                uuids: vec![],
                steps: 0,
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
