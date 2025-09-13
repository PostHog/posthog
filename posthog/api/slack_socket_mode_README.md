# Slack Socket Mode Integration

This implementation provides a Slack Socket Mode client that can handle real-time events, specifically responding to app mentions with "Hello world!".

## Setup

### 1. Slack App Configuration

You need to configure your Slack app to use Socket Mode:

1. Go to your Slack app configuration at https://api.slack.com/apps
2. Enable **Socket Mode** in the app settings
3. Generate an **App-Level Token** with `connections:write` scope
4. Subscribe to **Bot Events** and add the `app_mention` event
5. Add the bot to channels where you want it to respond to mentions
6. Note your **Bot User OAuth Token** from the OAuth & Permissions section

Required Bot Token Scopes:
- `app_mentions:read` - to receive mention events
- `chat:write` - to send messages
- `channels:read` - to access channel information

### 2. Environment Configuration

Set the following environment variables or instance settings:

```bash
SLACK_APP_TOKEN=xapp-1-xxxxx  # App-level token for Socket Mode
SLACK_BOT_TOKEN=xoxb-xxxxx    # Bot User OAuth Token
```

### 3. Running the Client

Start the Socket Mode client using the management command:

```bash
python manage.py run_slack_socket_mode
```

Or with command-line tokens:

```bash
python manage.py run_slack_socket_mode --app-token xapp-1-xxxxx --bot-token xoxb-xxxxx
```

## Usage

Once running, users in your Slack workspace can mention the bot in any channel where it's present:

```
@PostHogBot hello there!
```

The bot will respond with "Hello world! 👋" to any mention.

## Architecture

- **SlackSocketModeClient**: Main client class that handles Socket Mode connections
- **Management Command**: Django management command to run the client as a long-running process
- **Event Handlers**: Processes app mention events and other Slack events

## Extending

To add more event handlers or functionality:

1. Add new event handlers in `handle_events_api()` for different event types
2. Modify `handle_app_mention()` to add more sophisticated responses
3. Update the Slack app configuration to include new scopes/events as needed

## Notes

- Socket Mode is ideal for development and smaller deployments
- For production at scale, consider using the Events API with webhooks instead
- The client automatically handles reconnection if the connection drops
- All requests are properly acknowledged to avoid Slack retries
- The bot must be invited to channels to receive mentions in them