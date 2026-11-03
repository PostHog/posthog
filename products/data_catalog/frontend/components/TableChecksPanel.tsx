import { useActions } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { dataQualityCheckEditorLogic } from 'products/data_quality/frontend/dataQualityCheckEditorLogic'
import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'
import { SubjectChecksPanel } from 'products/data_quality/frontend/overview/SubjectChecksPanel'
import { SubjectRunBanners } from 'products/data_quality/frontend/overview/SubjectRunBanners'

import type { CatalogTableRow } from '../catalogTableRows'

export function TableChecksPanel({ row }: { row: CatalogTableRow }): JSX.Element {
    const { setLastActionCheck } = useActions(dataQualityOverviewLogic)
    const { openEditor } = useActions(dataQualityCheckEditorLogic)

    const addCheck = (): void => {
        if (!row.subject) {
            return
        }
        setLastActionCheck(null)
        openEditor(null, row.subject)
    }

    return (
        <div className="flex flex-col gap-2 py-2">
            {row.checkGroup ? (
                <>
                    <SubjectRunBanners group={row.checkGroup} />
                    <div className="overflow-x-auto">
                        <SubjectChecksPanel group={row.checkGroup} />
                    </div>
                </>
            ) : (
                <p className="mb-0 px-2 text-secondary">No checks on this table yet.</p>
            )}
            <div className="px-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlusSmall />}
                    onClick={addCheck}
                    disabledReason={row.subject ? undefined : "Checks can't be added to this table yet"}
                    data-attr="data-catalog-tables-add-check"
                >
                    Add check
                </LemonButton>
            </div>
        </div>
    )
}
