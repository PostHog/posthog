import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconNotebook as IconNotebookLegacy, LemonIconProps } from 'lib/lemon-ui/icons'
import { IconNotebook as IconNotebook3000 } from '@posthog/icons'

export function IconNotebook(props: LemonIconProps): JSX.Element {
    const is3000 = useFeatureFlag('POSTHOG_3000')

    return is3000 ? <IconNotebook3000 {...props} /> : <IconNotebookLegacy {...props} />
}
