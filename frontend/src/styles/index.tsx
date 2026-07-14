/// <reference types="vite/client" />
import '@posthog/tailwind/tailwind.css'

// global.scss must load AFTER tailwind so our base styles win the cascade
import './global.scss'

/* Contains PostHog's main styling configurations */

// Absorb HMR invalidations here: CSS deps hot-update on their own, but without this a stylesheet
// edit bubbles into src/index.tsx — and an invalidated entry double-boots the app under Vite 8
// (two createRoot calls) until the dev server restarts.
if (import.meta.hot) {
    import.meta.hot.accept()
}
