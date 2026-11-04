import { useActions } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Button, Text, cn } from '@posthog/quill'

import { CHECKS_CONTAINER } from 'products/data_quality/frontend/checkTableLayout'
import { dataQualityCheckEditorLogic } from 'products/data_quality/frontend/dataQualityCheckEditorLogic'
import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'
import { QuillSubjectChecksPanel } from 'products/data_quality/frontend/overview/QuillSubjectChecksPanel'
import { QuillSubjectRunBanners } from 'products/data_quality/frontend/overview/QuillSubjectRunBanners'

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
        <div className={cn(CHECKS_CONTAINER, 'flex flex-col gap-2 py-2')}>
            {row.checkGroup ? (
                <>
                    <QuillSubjectRunBanners group={row.checkGroup} />
                    <QuillSubjectChecksPanel group={row.checkGroup} />
                </>
            ) : (
                <Text size="xs" variant="muted" className="m-0">
                    No checks on this table yet.
                </Text>
            )}
            <div>
                <Button
                    variant="outline"
                    onClick={addCheck}
                    disabledReason={row.subject ? undefined : "Checks can't be added to this table yet"}
                    data-attr="data-catalog-tables-add-check"
                >
                    <IconPlus />
                    Add check
                </Button>
            </div>
        </div>
    )
}
