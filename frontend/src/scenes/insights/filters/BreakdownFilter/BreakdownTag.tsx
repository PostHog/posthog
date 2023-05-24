import { LemonTag } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { breakdownTagLogic } from './breakdownTagLogic'
import { BreakdownTagMenu } from './BreakdownTagMenu'

type BreakdownTagProps = {
    breakdown: string | number
    isTrends: boolean
}

export function BreakdownTag({ breakdown, isTrends }: BreakdownTagProps): JSX.Element {
    const logicProps = { breakdown, isTrends }
    const { isViewOnly, shouldShowMenu, propertyName } = useValues(breakdownTagLogic(logicProps))
    const { removeBreakdown } = useActions(breakdownTagLogic(logicProps))

    return (
        <BindLogic logic={breakdownTagLogic} props={logicProps}>
            <LemonTag
                className="taxonomic-breakdown-filter tag-pill"
                // display remove button only if we can edit and don't have a separate menu
                closable={!isViewOnly && !shouldShowMenu}
                onClose={removeBreakdown}
                popover={{
                    overlay: shouldShowMenu ? <BreakdownTagMenu /> : undefined,
                    closeOnClickInside: false,
                }}
            >
                <PropertyKeyInfo value={propertyName} />
            </LemonTag>
        </BindLogic>
    )
}
