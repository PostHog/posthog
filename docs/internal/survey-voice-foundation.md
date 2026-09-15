# Survey voice input foundation

`SurveyVoiceInput` provides recording controls under `products/surveys/frontend/voice/`.
Only Storybook mounts the component in this change.
It does not call a model, provide a transcription endpoint, or change any product screen.

## Contract

Each mounted input takes a unique `id`, an `onTranscript(text)` callback, and a `transcribe(audio, signal)` callback returning a promise of text.
The caller owns the editable answer and decides how to insert the transcript.
The component never submits a survey response.

The browser requests microphone access after the respondent clicks **Record an answer**.
The recording remains a local blob until the respondent clicks **Transcribe recording**, which invokes the supplied callback.
A local audio player lets the respondent preview it first.
The callback should honor the abort signal when the respondent discards the recording or leaves the form.
Late results are ignored even if the callback ignores cancellation.
A failed or empty transcription preserves the recording for retry.
Successful transcription releases the local blob after delivering the text to the caller.

Recording stops after one minute and rejects empty blobs or blobs larger than 5 MiB.
These client limits improve the recording experience; they are not server enforcement.
Microphone tracks, timers, and object URLs are released on discard or unmount.
Text input remains the caller's fallback when recording is unavailable.
The caller must disable response submission while recording or transcription is in progress if its form requires that behavior.

## Stories

`Surveys/Voice input` includes the recorder at two widths, a disabled state, and a transcription failure.
The stories use browser microphone capture with a mock transcription callback.
They do not upload audio or call models.
The answer remains editable after the sample transcript arrives.

## Future transcription endpoint

Choose the provider with a comparison of the same short recordings, including accents, background noise, and product terminology.
Measure transcription errors, omitted or invented details, latency, and cost.
A low-cost multimodal model and a dedicated speech-to-text model are both candidates; this foundation does not select one.

A production endpoint must validate real audio format and duration, enforce tenant access and sustained usage limits, and implement the applicable AI consent settings.
It must use the existing PostHog AI observability integration with transcript and audio capture disabled unless explicitly required.
Verify instrumentation for the actual provider method: an instrumented client does not necessarily cover every API endpoint.
Provider credentials and model calls belong on the server.
Replay association, product context, rollout, and experiments comparing response quality remain separate integrations.
