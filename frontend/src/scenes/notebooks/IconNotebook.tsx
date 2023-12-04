import { IconNotebook as IconNotebook3000 } from '@posthog/icons'
import { useValues } from 'kea'
import { IconNotebook as IconNotebookLegacy, LemonIconProps } from 'lib/lemon-ui/icons'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export function IconNotebook(props: LemonIconProps): JSX.Element {
    const { is3000 } = useValues(themeLogic)

    return is3000 ? <IconNotebook3000 {...props} /> : <IconNotebookLegacy {...props} />
}
