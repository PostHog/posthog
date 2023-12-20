import { IconNotebook as IconNotebook3000 } from '@posthog/icons'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconNotebook as IconNotebookLegacy, LemonIconProps } from 'lib/lemon-ui/icons'

export function IconNotebook(props: LemonIconProps): JSX.Element {
    const is3000 = useFeatureFlag('POSTHOG_3000', 'test')

    return is3000 ? <IconNotebook3000 {...props} /> : <IconNotebookLegacy {...props} />
}
