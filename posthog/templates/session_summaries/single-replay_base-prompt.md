You will be generating a summary of a user session on a website based on a series of events. The events data:

<events_data>
{{EVENTS_DATA}}
</events_data>

Each event in the data is a tuple containing the following information:
1. Event type
2. Timestamp
3. Elements chain href
4. Elements chain texts
5. Elements chain elements
6. Window ID
7. Current URL
8. Event subtype (if applicable)

Your task is to analyze these events chronologically and create a concise, readable summary of the user's session. Follow these steps:

1. Examine the events in the order they occurred.

2. Interpret the different event types:
   - '$pageview': Indicates the user visited a new page
   - '$autocapture': Represents user interactions like clicks or form submissions
   - 'client_request_failure': Suggests an error or failed request
   - '$web_vitals': Relates to page performance metrics
   - and others, get their meaning from the context

3. Pay special attention to:
   - The URLs visited (found in the 'current_url' field)
   - User interactions (clicks, form submissions) in '$autocapture' events
   - Any error events

4. Create a narrative of the user's journey through the site, focusing on:
   - Pages visited
   - Actions taken (clicks, form submissions)
   - Any errors or issues encountered

5. Generate a concise summary of the session, highlighting the key events and user actions.

Provide your summary inside <summary> tags. The summary should be a short paragraph, typically 3-5 sentences, that captures the essence of the user's session.