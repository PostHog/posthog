import { PaperDeskThemeProvider } from 'scenes/authentication/shared/paperDesk/PaperDeskScene'

import { PaperDeskSignup } from '../paper-desk/PaperDeskSignup'

/** The paper-desk page re-skinned with posthog.com's garden design language - behavior unchanged. */
export function GlassSignup(): JSX.Element {
    return (
        <PaperDeskThemeProvider theme="glass">
            <PaperDeskSignup />
        </PaperDeskThemeProvider>
    )
}
