# Desktop feedback

People can select **Send feedback…** from the account menu, use the command menu, or press `Cmd+Shift+F` on macOS and `Ctrl+Shift+F` on other systems.
In the form, press `Cmd+Enter` or `Ctrl+Enter` to send feedback.
Select **Bug**, **Feature**, or **General** from **Feedback type**. The default is **General**.
The form shown before opening PostHog web does not ask for a feedback type.

The form sends one authenticated request to the Desktop feedback endpoint. The `desktop-feedback-conversations` flag selects the destination. When enabled, the endpoint creates a Support ticket in the regional internal feedback project. Otherwise, it submits a response to the existing Desktop feedback survey. A submission never creates both records. Each record includes the current view, app version, session, and related task or folder ID when available.

Ticket replies use the sender's verified account email. The internal feedback project must have Support and email enabled, with an active, verified default Support email channel. The endpoint rejects a ticket submission if replies are not configured. It does not silently submit a survey response instead.

The endpoint accepts an optional `feedback_type`: `bug`, `feature`, or `general`. The survey event stores this value. Older app versions can omit this field.

The app captures the current window before the form opens. The screenshot can be reviewed and stays off until selected. People can attach up to two images with **Attach images** or paste them into the message. Both methods use the same image checks and limit. Image previews open after attachment, and images can be removed before sending. Text paste still works. If another image is still loading, the form asks the user to wait and paste again. Files without a MIME type use their image signature; files with an incorrect or unsupported format are rejected. Recent app logs can be reviewed while they stay off, and are sent only when selected.

Selected screenshots and images are stored in PostHog's internal media project, not the project selected in Desktop. Tickets and legacy survey responses contain authenticated image links instead of image data. Only people with access to the internal feedback project can open them, and the public media route returns `404`. Links stop working after 30 days, and a daily cleanup removes the stored media. If the submission fails, the endpoint removes the new media. Ticket logs are private notes, not customer-facing replies. The feedback modal is excluded from Session Replay, so previews and logs do not enter the recording.

Tickets retain the session identifier. Legacy survey events keep their normal session link, so authorized reviewers can inspect the app state before the modal opened.

Keep past survey responses. New ticket feedback goes through the Support review flow, not the surveys scout. Existing clients can keep using the same endpoint and response shape. The `response_id` is the ticket ID when ticket routing is enabled.

Deploy the backend before enabling the flag. First enable it for test accounts in each region. Check ticket creation, private image access, an outbound email reply, and the customer's reply in the same ticket. Check that new submissions do not also emit `survey sent`. Disable the flag to return new submissions to the survey. Existing tickets remain available.

The optional `feedback_type` from the feedback-type API change is preserved in ticket context. That API change can deploy independently. The mobile report-launch changes do not affect this route.
