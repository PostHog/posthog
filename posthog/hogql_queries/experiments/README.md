# Experiment query runner documentation

## Funnel evaluation expression

As the query construction to meet the `aggregate_funnel_array` input format is somewhat complex,
this explains the different parts in more detail.

## Funnel step pre-calculation

To avoid property resolution issues when using property filters in funnel steps (e.g., filtering events by `wizard_step = "step_1"`), the experiment query runner requires that step conditions are pre-calculated in the metric events query rather than resolving them inside the UDF.

### Step condition pre-calculation in metric events query

In `_get_metric_events_query()` for funnel metrics, step conditions are calculated as separate columns:

```sql
SELECT
    events.timestamp,
    events.person_id AS entity_id,
    exposure_data.variant,
    events.event,
    events.uuid,
    events.properties,
    if(and(equals(events.event, '$pageview'), equals(events.properties.wizard_step, 'step_1')), 1, 0) AS step_0,
    if(and(equals(events.event, '$pageview'), equals(events.properties.wizard_step, 'step_2')), 1, 0) AS step_1
FROM events
INNER JOIN exposure_data ON events.person_id = exposure_data.entity_id
WHERE ...
```

**Benefits of this approach:**

- **Property resolution**: Complex property filters (including nested properties) are resolved at the SQL level where the HogQL type system works correctly
- **Performance**: Property filtering happens early in the query pipeline
- **Compatibility**: Works with all property types and operators without UDF limitations

### UDF step condition construction

The `funnel_evaluation_expr()` function uses the pre-calculated step conditions:

```sql
multiply(1, metric_events.step_0),
multiply(2, metric_events.step_1),
```

- **Purpose**: Creates numeric step identifiers for each event
- **Logic**: If event matches the step condition, return the step number (1, 2, 3), otherwise 0
- **Result**: Each event gets tagged with which funnel steps it satisfies

### 2. Events array construction

This is the main input to the `aggregate_funnel_array` function. This part of the query simply transforms the events for each
user into the format required by the function. It requires an array of tuples, where each element represents an event for that
user, it's timestamp and whether it satisfies any of the steps in the funnel or not.

```sql
arraySort(t -> t.1, groupArray(tuple(
    timestamp_float,                   -- Sort key: timestamp
    uuid,                              -- Event identifier
    array(''),                         -- Breakdown value (empty = no breakdown)
    arrayFilter(x -> x != 0, [...])    -- Step numbers this event matches
)))
```

- **Purpose**: Creates the main input array for the UDF
- **Sorting**: Events are sorted by timestamp (t.1) to ensure chronological order
- **Filtering**: `arrayFilter(x -> x != 0, [...])` removes zeros, leaving only actual step numbers
- **Example result**: `[(1704110400.0, uuid1, '', [1]), (1704110700.0, uuid2, '', [2])]`

### 3. UDF function call

```sql
aggregate_funnel_array(
    3,                    -- Number of steps in funnel
    3600,                 -- Conversion window: 1 hour
    'first_touch',        -- Attribution: use first occurrence of breakdown
    'ordered',            -- Order: events must happen in sequence
    array(array('')),     -- Breakdown values, empty -> no breakdown
    events_array          -- Preprocessed events data as above
)
```

- **Purpose**: Performs the funnel analysis logic
- **Window**: 3600 seconds = 1 hour maximum between first and last step
- **Attribution**: Which attribution type to use. Only relevant if using breakdowns. We don't.
- **Ordering**: 'ordered' means step 2 must come after step 1, step 3 after step 2
- **Returns**: Array of tuples with results for each user

### 4. Result output

The UDF returns tuples with this structure:

- **`step_reached`**: Highest step completed (0-indexed, so 2 = completed all 3 steps)
- **`breakdown_values`**: Array of breakdown property values (empty in our case)
- **`conversion_times`**: Array of seconds between steps [step1→step2, step2→step3]
- **`event_uuids`**: Arrays of UUIDs for events used in each step

### 5. Result evaluation

Finally, we evaluate whether the user completed the full funnel (return 1) or not (return 0).
`aggregate_funnel_array` returns an array of tuples for each user (One for each breakdown value?
We don't care about breakdown values so there will only be one element in the array). We then
filter the array first to only keep the element if the funnel was completed,
i.e `step_reached >= num_steps - 1` (`step_reached` is 0-indexed).
Finally, if the list is not empty (`length > 0`), we return 1, otherwise 0.

## Parameter configurability

Experiments support configurable statistical parameters through the `stats_config` field. This allows users to customize the behavior of both Bayesian and Frequentist statistical methods.

### Configuration structure

The `stats_config` field is a JSON object with method-specific keys:

```json
{
  "bayesian": {
    "ci_level": 0.95,
    "difference_type": "RELATIVE",
    "inverse": false,
    "proper_prior": false,
    "prior_type": "RELATIVE",
    "prior_mean": 0.0,
    "prior_variance": 1.0
  },
  "frequentist": {
    "alpha": 0.05,
    "test_type": "TWO_SIDED",
    "difference_type": "RELATIVE"
  }
}
```

### Bayesian parameters

- **`ci_level`** (float, default: 0.95): Credible interval level, must be between 0 and 1
- **`difference_type`** (string, default: "RELATIVE"): Type of difference calculation
  - `"RELATIVE"`: Percentage change from baseline
  - `"ABSOLUTE"`: Absolute difference from baseline
- **`inverse`** (bool, default: false): Whether lower values are better
- **`proper_prior`** (bool, default: false): Whether to use an informative prior
- **`prior_type`** (string, default: "RELATIVE"): Type of prior to use
  - `"RELATIVE"`: Prior relative to baseline
  - `"ABSOLUTE"`: Absolute prior
- **`prior_mean`** (float, default: 0.0): Mean of the prior distribution
- **`prior_variance`** (float, default: 1.0): Variance of the prior distribution (must be non-negative)

### Frequentist parameters

- **`alpha`** (float, default: 0.05): Significance level, must be between 0 and 1
- **`test_type`** (string, default: "TWO_SIDED"): Type of hypothesis test
  - `"TWO_SIDED"`: Test for any difference
  - `"ONE_SIDED"`: Test for improvement in one direction
- **`difference_type`** (string, default: "RELATIVE"): Type of difference calculation
  - `"RELATIVE"`: Percentage change from baseline
  - `"ABSOLUTE"`: Absolute difference from baseline

### Validation and defaults

- Invalid numeric values (out of range or non-numeric) fall back to defaults
- Invalid enum values (typos or wrong types) fall back to defaults
- Missing parameters use defaults
- `null` or empty config uses all defaults
