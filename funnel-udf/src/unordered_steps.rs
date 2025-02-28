use crate::PropVal;
use itertools::Itertools;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::VecDeque;
use std::iter::repeat;
use uuid::Uuid;

#[derive(Clone, Deserialize)]
struct EnteredTimestamp {
    timestamp: f64,
    excluded: bool,
    timings: Vec<f64>,
    uuids: Vec<Uuid>,
}

#[derive(Clone, Deserialize)]
struct Event {
    timestamp: f64,
    uuid: Uuid,
    breakdown: PropVal,
    steps: Vec<i8>,
}

#[derive(Deserialize)]
struct Args {
    num_steps: usize,
    conversion_window_limit: u64, // In seconds
    breakdown_attribution_type: String,
    funnel_order_type: String,
    prop_vals: Vec<PropVal>,
    value: Vec<Event>,
}

#[derive(Serialize)]
struct Result(i8, PropVal, Vec<f64>, Vec<Vec<Uuid>>);

struct Vars {
    max_step: (usize, EnteredTimestamp),
    events_by_step: Vec<VecDeque<Event>>,
    num_steps_completed: usize,
}

struct AggregateFunnelRow {
    breakdown_step: Option<usize>,
    results: Vec<Result>,
}

const MAX_REPLAY_EVENTS: usize = 10;

const DEFAULT_ENTERED_TIMESTAMP: EnteredTimestamp = EnteredTimestamp {
    timestamp: 0.0,
    excluded: false,
    timings: vec![],
    uuids: vec![],
};

pub fn process_line(line: &str) -> Value {
    let args = parse_args(line);
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
            // For each step, we store a deque of events (in chronological order) that have reached that step
            events_by_step: repeat(VecDeque::new()).take(args.num_steps).collect(),
            // Max step keeps track of the place where we have matched the most events
            max_step: (0, DEFAULT_ENTERED_TIMESTAMP.clone()),
            num_steps_completed: 0,
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

            if events_with_same_timestamp.len() == 1 {
                self.process_event(args, &mut vars, events_with_same_timestamp[0], prop_val);
            } else {
                // Split events into those with negative steps (exclusions) and positive steps
                let (exclusion_events, step_events): (Vec<_>, Vec<_>) = events_with_same_timestamp
                    .iter()
                    .partition(|&event| event.steps.iter().all(|&step| step < 0));

                if exclusion_events.is_empty() {
                    for event in events_with_same_timestamp {
                        self.process_event(args, &mut vars, event, prop_val);
                    }
                } else {
                    // Handle permutations for different events with the same timestamp
                    // First run the steps (positive values)
                    for event in step_events {
                        self.process_event(args, &mut vars, event, prop_val);
                    }

                    // Then run the exclusions (negative values)
                    for event in exclusion_events {
                        self.process_event(args, &mut vars, event, prop_val);
                    }

                    // Then run the steps again to ensure proper processing
                    for event in step_events {
                        self.process_event(args, &mut vars, event, prop_val);
                    }
                }
            }
        }

        // Find the furthest step we have made it to and print it
        let final_index = vars.max_step.0;
        let final_value = &vars.max_step.1;

        if final_value.excluded {
            self.results
                .push(Result(-1, prop_val.clone(), vec![], vec![]));
            return;
        }

        for i in 0..final_index {
            //if event_uuids[i].len() >= MAX_REPLAY_EVENTS && !event_uuids[i].contains(&final_value.uuids[i]) {
            // Always put the actual event uuids first, we use it to extract timestamps
            // This might create duplicates, but that's fine (we can remove it in clickhouse)
            vars.event_uuids[i].insert(0, final_value.uuids[i].clone());
        }
        self.results.push(Result(
            final_index as i8 - 1,
            prop_val.clone(),
            final_value
                .timings
                .windows(2)
                .map(|w| w[1] - w[0])
                .collect(),
            vars.event_uuids,
        ))
    }

    #[inline(always)]
    fn process_event(&mut self, args: &Args, vars: &mut Vars, event: &Event, prop_val: &PropVal) {
        if event.steps[0] < 0 {
            // TODO
            // exclusion - set exclusion on max_steps and if they get another event, remove the user
            return;
        }

        // 1. Push the event to the back of the deque. If it matches multiple steps, push it to the one whose last element is the further from now
        // 2. Delete all events that are out of the match window
        // 3. Update some value to store the size of the match now (so we know if we can update max without iterating through them all again)

        // If it matches one step, update that step
        // The assumption here is that there is only one way to fulfill each step. For example, if the same event fulfills steps 2 and 7, there is no other event
        // that fulfills just step 2. If we add that functionality, this gets more complicated.
        let min_timestamp_step = *event
            .steps
            .iter()
            .min_by_key(|&&step| {
                let step = step as usize;
                vars.events_by_step[step]
                    .back()
                    .map(|e| e.timestamp)
                    .unwrap_or(0.0);
            })
            .unwrap() as usize;

        if vars.events_by_step[min_timestamp_step].is_empty() {
            vars.num_steps_completed += 1;
        }
        vars.events_by_step[min_timestamp_step].push_back(event.clone());

        // 2. Delete all events that are out of the match window
        for step in 0..vars.events_by_step.len() {
            if !vars.events_by_step[step].is_empty() {
                loop {
                    let front_event = vars.events_by_step[step].front();
                    if front_event.is_none() {
                        vars.num_steps_completed -= 1;
                        break;
                    }

                    let front_event = front_event.unwrap();
                    if event.timestamp - front_event.timestamp > args.conversion_window_limit as f64
                    {
                        vars.events_by_step[step].pop_front();
                    } else {
                        break;
                    }
                }
            }
        }

        // 3. Update max_step if we've completed more steps than before
        if vars.num_steps_completed > vars.max_step.0 {
            let mut timestamps_with_uuids: Vec<(f64, Uuid)> = vars
                .events_by_step
                .iter()
                .filter_map(|deque| deque.front().map(|e| (e.timestamp, e.uuid)))
                .collect();

            timestamps_with_uuids.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());

            let timings = timestamps_with_uuids
                .windows(2)
                .map(|w| w[1].0 - w[0].0)
                .collect::<Vec<f64>>();
            let uuids = timestamps_with_uuids
                .iter()
                .map(|(_, u)| *u)
                .collect::<Vec<Uuid>>();

            vars.max_step = (
                vars.num_steps_completed,
                EnteredTimestamp {
                    timestamp: event.timestamp,
                    excluded: false,
                    timings: timings,
                    uuids: uuids,
                },
            );
        }
    }
}
