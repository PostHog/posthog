import { PaperDeskThemeProvider } from 'scenes/authentication/shared/paperDesk/PaperDeskScene'

import { PaperDeskVerifyEmail } from '../paper-desk/PaperDeskVerifyEmail'

/** The paper-desk page re-skinned with posthog.com's garden design language - behavior unchanged. */
export function GlassVerifyEmail(): JSX.Element {
    return (
        <PaperDeskThemeProvider theme="glass">
            <PaperDeskVerifyEmail />
        </PaperDeskThemeProvider>
    )
}
