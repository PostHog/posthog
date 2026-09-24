import { useValues } from 'kea'

import { IconDownload } from '@posthog/icons'

import { IconWithCount } from 'lib/lemon-ui/icons'

import { sidePanelExportsLogic } from './sidePanelExportsLogic'

export const SidePanelExportsIcon = (): JSX.Element => {
    const { freshUndownloadedExports } = useValues(sidePanelExportsLogic)
    return (
        <IconWithCount count={freshUndownloadedExports.length}>
            <IconDownload />
        </IconWithCount>
    )
}
