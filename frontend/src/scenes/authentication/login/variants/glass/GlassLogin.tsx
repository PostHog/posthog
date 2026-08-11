import { PaperDeskThemeProvider } from 'scenes/authentication/shared/paperDesk/PaperDeskScene'

import { PaperDeskLogin } from '../paper-desk/PaperDeskLogin'

/** The paper-desk page re-skinned with posthog.com's garden design language - behavior unchanged. */
export function GlassLogin(): JSX.Element {
    return (
        <PaperDeskThemeProvider theme="glass">
            <PaperDeskLogin />
        </PaperDeskThemeProvider>
    )
}
