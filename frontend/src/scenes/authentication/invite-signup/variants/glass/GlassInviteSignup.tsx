import { PaperDeskThemeProvider } from 'scenes/authentication/shared/paperDesk/PaperDeskScene'

import { PaperDeskInviteSignup } from '../paper-desk/PaperDeskInviteSignup'

/** The paper-desk page re-skinned with posthog.com's garden design language - behavior unchanged. */
export function GlassInviteSignup(): JSX.Element {
    return (
        <PaperDeskThemeProvider theme="glass">
            <PaperDeskInviteSignup />
        </PaperDeskThemeProvider>
    )
}
