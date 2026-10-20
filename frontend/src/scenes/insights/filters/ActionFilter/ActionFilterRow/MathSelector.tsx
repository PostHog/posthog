import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { LemonMathSelector } from './LemonMathSelector'
import { QuillMathSelector } from './QuillMathSelector'
import type { MathSelectorProps } from './types'

export function MathSelector(props: MathSelectorProps): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillMathSelector {...props} /> : <LemonMathSelector {...props} />
}
