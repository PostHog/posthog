# AI feedback with surveys disabled

AI feedback setup creates an API survey without changing the project's **Enable surveys** setting.
Captured feedback remains visible in the trace's feedback tab while that setting is off.
The feedback tab does not ask users to enable other running surveys.

The React example uses `useThumbSurvey` to record the rating and display optional follow-up questions.
When project-wide surveys are disabled, the browser SDK does not automatically fetch survey definitions.
The example subscribes through `posthog.onSurveysLoaded`, which loads the definitions after the survey SDK initializes.
Feedback buttons remain disabled until the selected survey is available.
If loading fails or the survey is missing, the example asks the user to refresh and try again.
The subscription is removed when the component unmounts.

Integrations that send `survey sent` events directly do not need to load survey definitions or enable project-wide surveys.

For in-app surveys launched through either survey editor, the launch confirmation includes an **Enable surveys for this project** checkbox when the project setting is off.
Leaving it checked enables every running in-app survey in the project.
Unchecking it launches the selected survey while leaving automatic display disabled.
API and hosted surveys do not change that project setting when launched.
