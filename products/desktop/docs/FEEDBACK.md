# Desktop feedback

People can select **Send feedback…** from the account menu, use the command menu, or press `Cmd+Shift+F` on macOS and `Ctrl+Shift+F` on other systems.
In the form, press `Cmd+Enter` or `Ctrl+Enter` to send feedback.

The form sends one authenticated request to the Desktop feedback endpoint. The endpoint records the response in the Desktop feedback survey only after it accepts the full submission. Each response includes the current view, app version, session, and related task or folder ID when available.

The app captures the current window before the form opens. The screenshot can be reviewed and stays off until selected. People can also attach up to two images. Recent app logs can be reviewed while they stay off, and are sent only when selected.

Selected screenshots and images are stored in PostHog's internal media project, not the project selected in Desktop. The survey response contains image links instead of image data. If the response fails, the endpoint removes the new media. The feedback modal is excluded from Session Replay, so previews and logs do not enter the recording.

The survey event keeps its normal session link, so authorized reviewers can inspect the app state before the modal opened.

The Signals surveys scout can review these responses. It groups open-text answers into recurring themes and files what it finds in the Signals inbox.
