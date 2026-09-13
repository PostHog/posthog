import { setGetHelpAction } from 'lib/lemon-ui/LemonToast/getHelp'

import { openInAppSupport } from './openInAppSupport'

/** Points the error toast's "Get help" button at in-app support instead of the docs fallback. */
export function registerToastGetHelp(): void {
    setGetHelpAction(openInAppSupport)
}
