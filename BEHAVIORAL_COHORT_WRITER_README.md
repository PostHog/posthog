# Behavioral Cohort Writer - POC

This is a proof of concept implementation for writing behavioral cohort matches to a file during event ingestion.

## What it does

1. **Intercepts events** during the ingestion pipeline
2. **Checks for behavioral cohort matches** by comparing event names against cohort definitions
3. **Writes matches to a log file** at `/tmp/posthog-behavioral-cohorts/behavioral-cohort-matches.jsonl`

## Files Added/Modified

### New Files:
- `plugin-server/src/worker/ingestion/event-pipeline/behavioral-cohort-writer.ts` - Main implementation
- `test-behavioral-cohort.js` - Manual test script

### Modified Files:
- `plugin-server/src/worker/ingestion/event-pipeline/runner.ts` - Added the step to the pipeline

## How to Test

### 1. Set up a test cohort

Run the test script to create a test cohort:

```bash
node test-behavioral-cohort.js
```

This will:
- Create a test cohort with behavioral filters
- Show you the curl command to send a test event

### 2. Send a test event

Use the curl command provided by the script, or send an event through your normal PostHog setup.

### 3. Check the log file

```bash
tail -f /tmp/posthog-behavioral-cohorts/behavioral-cohort-matches.jsonl
```

You should see entries like:
```json
{"timestamp":"2024-01-15T10:30:00.000Z","team_id":1,"team_name":"Test Team","cohort_id":144987,"cohort_name":"Power Users","event_name":"insight analyzed","distinct_id":"user123","properties":{"test":"value"},"uuid":"event-uuid"}
```

### 4. Verify TypeScript compilation

```bash
cd plugin-server
npm run typescript:check
```

## How it works

1. **Pipeline Integration**: The `behavioralCohortWriterStep` is added to the event pipeline after `transformEventStep` but before `normalizeEventStep`

2. **Cohort Loading**: For each team, it loads cohorts that contain behavioral filters (detected by checking if `properties` contains the string 'behavioral')

3. **Event Matching**: It extracts behavioral filters from cohort properties and checks if the incoming event matches any of them

4. **File Writing**: When a match is found, it writes the event details to a JSON Lines file

## Performance Considerations

- **Caching**: Behavioral cohorts are cached per team with a 1-minute TTL
- **Async**: All file operations are asynchronous
- **Error Handling**: Errors don't fail the pipeline - they're logged but the event continues processing
- **Minimal Impact**: Only processes events for teams that have behavioral cohorts

## Example Cohort Structure

The system looks for cohorts with this structure:

```json
{
  "properties": {
    "type": "AND",
    "values": [
      {
        "type": "OR", 
        "values": [
          {
            "type": "OR",
            "values": [
              {
                "key": "insight analyzed",
                "type": "behavioral",
                "value": "performed_event_multiple",
                "operator": "gte",
                "operator_value": 5,
                "explicit_datetime": "-30d",
                "negation": false
              }
            ]
          }
        ]
      }
    ]
  }
}
```

## Next Steps

This POC demonstrates that we can:
1. ✅ Extract behavioral filters from cohort definitions
2. ✅ Match events against those filters during ingestion
3. ✅ Write the matches somewhere (file in this case)

The next step would be to:
1. Replace file writing with Redis counters
2. Add logic to evaluate the full behavioral criteria (counts, time windows, etc.)
3. Integrate with the existing cohort evaluation system
4. Add proper HogFunction support for behavioral cohort checks

## Log File Format

Each line in the log file is a JSON object with:
- `timestamp`: When the match occurred
- `team_id`: PostHog team ID
- `team_name`: Team name
- `cohort_id`: ID of the matching cohort
- `cohort_name`: Name of the matching cohort
- `event_name`: Name of the event that matched
- `distinct_id`: User who triggered the event
- `properties`: Event properties
- `uuid`: Event UUID