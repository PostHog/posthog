# Desktop feedback

People can select **Send feedback…** from the account menu, use the command menu, or press `Cmd+Shift+F` on macOS and `Ctrl+Shift+F` on other systems.
In the form, press `Cmd+Enter` or `Ctrl+Enter` to send feedback.
Select **Bug**, **Feature**, or **General** from **Feedback type**. The default is **General**.
The form shown before opening PostHog web does not ask for a feedback type.

The form sends one authenticated request to the Desktop feedback endpoint. The endpoint records the response in the Desktop feedback survey only after it accepts the full submission. Each response includes the current view, app version, session, and related task or folder ID when available.

The endpoint accepts an optional `feedback_type`: `bug`, `feature`, or `general`. The survey event stores this value. Older app versions can omit this field.

The app captures the current window before the form opens. The screenshot can be reviewed and stays off until selected. People can attach up to two images with **Attach images** or paste them into the message. Both methods use the same image checks and limit. Image previews open after attachment, and images can be removed before sending. Text paste still works. If another image is still loading, the form asks the user to wait and paste again. Files without a MIME type use their image signature; files with an incorrect or unsupported format are rejected. Recent app logs can be reviewed while they stay off, and are sent only when selected.

Selected screenshots and images are stored in PostHog's internal media project, not the project selected in Desktop. The survey response contains authenticated image links instead of image data. Only people with access to the internal feedback project can open them, and the public media route returns `404`. Links stop working after 30 days, and a daily cleanup removes the stored media. If the response fails, the endpoint removes the new media. The feedback modal is excluded from Session Replay, so previews and logs do not enter the recording.

The survey event keeps its normal session link, so authorized reviewers can inspect the app state before the modal opened.

The Signals surveys scout can review these responses. It groups open-text answers into recurring themes and files what it finds in the Signals inbox.
