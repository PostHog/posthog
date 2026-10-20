import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { LemonTaxonomicBreakdownButton, LemonTaxonomicBreakdownButtonProps } from './LemonTaxonomicBreakdownButton'
import { QuillTaxonomicBreakdownButton } from './QuillTaxonomicBreakdownButton'

export function TaxonomicBreakdownButton(props: LemonTaxonomicBreakdownButtonProps): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? (
        <QuillTaxonomicBreakdownButton disabledReason={props.disabledReason} />
    ) : (
        <LemonTaxonomicBreakdownButton {...props} />
    )
}
