# Synthetic Monitoring UI - Testing Guide

## ✅ What's Ready

### Frontend Components Created:
1. **SyntheticMonitoring.tsx** - Main list view with tabs
2. **MonitorsTable.tsx** - Table showing all monitors with actions
3. **SyntheticMonitor.tsx** - Create/edit monitor form
4. **Routing configured** - URLs and scene registration complete

### Backend Ready:
- API endpoints working at `/api/projects/:id/synthetic_monitors/`
- Database migrations applied
- Models ready

## 🚀 How to Test the UI

### Step 1: Start PostHog

```bash
./bin/start
```

Wait for all services to start (Django, Celery, ClickHouse, PostgreSQL, frontend, etc.)

### Step 2: Access the Synthetic Monitoring UI

Open your browser and navigate to:

```
http://localhost:3000/synthetic-monitoring
```

Or from within PostHog, manually navigate to that URL.

### Step 3: What You'll See

**Main Page** (`/synthetic-monitoring`):
- "Synthetic Monitoring" header
- "New monitor" button (top right)
- Two tabs: "Monitors" and "Settings"
- Initially empty state with "Create monitor" button

**Create Monitor Page** (`/synthetic-monitoring/new`):
- Form with 3 sections:
  1. **Configure monitor**: Name, URL, Method, Status code, Frequency, Timeout, Request body
  2. **Select locations**: AWS regions dropdown (multi-select)
  3. **Alerts**: Enable alerts checkbox, failure threshold

**Edit Monitor Page** (`/synthetic-monitoring/:id`):
- Same form as create, but pre-populated with existing monitor data

### Step 4: Create a Test Monitor

1. Click "New monitor" button
2. Fill in the form:
   - **Name**: "Test Monitor"
   - **URL**: "https://posthog.com"
   - **Method**: GET (default)
   - **Expected status code**: 200
   - **Check frequency**: Every 5 minutes
   - **Timeout**: 30 seconds
   - **Regions**: Select "US East (N. Virginia)"
   - **Enable alerts**: Checked
   - **Alert threshold**: 3 consecutive failures
3. Click "Save monitor"

### Step 5: View Monitor in Table

After creating, you'll be redirected to the main page where you'll see:
- Monitor name and URL
- Status badge (initially "Healthy")
- HTTP method
- Frequency (5 min)
- Selected regions
- Last checked time
- Failure count
- Actions menu (Edit, Test now, Pause, Delete)

### Step 6: Test Monitor Actions

**Test Now**:
- Click the "More" (⋯) button on a monitor row
- Select "Test now"
- This triggers an immediate check via the API

**Edit**:
- Click "Edit" to modify the monitor
- Make changes and save

**Pause/Resume**:
- Pause to disable monitoring
- Resume to re-enable

**Delete**:
- Permanently remove the monitor

## 🔧 Integration with Your External Lambda

Since you have the Lambda working elsewhere, you can:

1. **Option A**: Keep using direct HTTP execution for MVP
   - The backend is already set up to execute HTTP checks directly
   - No Lambda integration needed for UI testing

2. **Option B**: Integrate your Lambda later
   - The UI doesn't care how checks are executed
   - Backend API remains the same
   - Just swap the execution method in `execute_http_check` task

## 📊 Viewing Check Results

Currently, check results are stored as events in ClickHouse. To view them:

### Via ClickHouse:
```bash
docker exec -it posthog-clickhouse clickhouse-client

SELECT
    timestamp,
    JSONExtractString(properties, 'monitor_name') as monitor,
    JSONExtractString(properties, 'url') as url,
    JSONExtractString(properties, 'region') as region,
    JSONExtractBool(properties, 'success') as success,
    JSONExtractInt(properties, 'status_code') as status_code,
    JSONExtractInt(properties, 'response_time_ms') as response_time_ms,
    JSONExtractString(properties, 'error_message') as error
FROM events
WHERE event = 'synthetic_http_check'
ORDER BY timestamp DESC
LIMIT 10
FORMAT Pretty;
```

### Via Django Admin:
```
http://localhost:8000/admin/posthog/syntheticmonitor/
```

View and modify monitors directly in the database.

## 🐛 Troubleshooting

### UI doesn't load:
- Check frontend console for errors
- Ensure `./bin/start` is running successfully
- Check that all TypeScript compiles without errors

### Monitors don't save:
- Check browser network tab for API errors
- Check Django logs for validation errors
- Verify team_id in the URL

### Can't see monitors:
- Check that you're logged in with correct team
- Verify monitors exist in Django admin
- Check API response: `curl http://localhost:8000/api/projects/{team_id}/synthetic_monitors/`

## 📝 Next Steps

After testing the UI, you can:

1. **Add navigation** - Add link in main menu (left sidebar)
2. **Improve results display** - Create a results/history page
3. **Add charts** - Visualize uptime and latency trends
4. **Integrate your Lambda** - Swap execution method
5. **Add tests** - Jest tests for components, pytest for API

## 🎨 UI Features Implemented

✅ List view with status badges
✅ Create/edit forms with validation
✅ Multi-region selection
✅ Alert configuration
✅ Pause/resume/delete actions
✅ Test now trigger
✅ Empty states
✅ Loading states
✅ Toast notifications
✅ Responsive layout

## 🔗 Useful URLs

- **Synthetic Monitoring**: http://localhost:3000/synthetic-monitoring
- **New Monitor**: http://localhost:3000/synthetic-monitoring/new
- **Django Admin**: http://localhost:8000/admin/
- **API Docs**: http://localhost:8000/api/projects/{team_id}/synthetic_monitors/
