import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { CertificationTargetType, certificationsLogic } from '../certificationsLogic'

const VIEW_TABLE_TYPES = new Set(['view', 'materialized_view', 'managed_view'])

function targetTypeForTable(tableType: string): CertificationTargetType | null {
    if (tableType === 'data_warehouse') {
        return 'table'
    }
    if (VIEW_TABLE_TYPES.has(tableType)) {
        return 'view'
    }
    return null
}

export function NewCertificationModal(): JSX.Element {
    const { newCertificationModalOpen, newCertificationForm, isCreatingCertification } = useValues(certificationsLogic)
    const { setNewCertificationForm, createCertification, closeNewCertificationModal } = useActions(certificationsLogic)
    const { allTables, databaseLoading } = useValues(databaseTableListLogic)

    // Certification targets are keyed by (type, name), so a warehouse table and a view sharing a
    // name are distinct targets. Encode the type into the option value so they don't collapse.
    const optionEntries = allTables
        .map((table) => ({ table, targetType: targetTypeForTable(table.type) }))
        .filter(
            (option): option is { table: (typeof allTables)[number]; targetType: CertificationTargetType } =>
                option.targetType !== null
        )
        .map(({ table, targetType }) => ({
            value: `${targetType}:${table.name}`,
            name: table.name,
            targetType,
        }))

    const options = optionEntries.map(({ value, name, targetType }) => ({
        value,
        label: name,
        labelInMenu: `${name} (${targetType})`,
    }))

    const selectedValue = newCertificationForm.targetName
        ? `${newCertificationForm.targetType}:${newCertificationForm.targetName}`
        : null

    const submitDisabledReason = !newCertificationForm.targetName ? 'Choose a table or view' : undefined

    return (
        <LemonModal
            isOpen={newCertificationModalOpen}
            onClose={closeNewCertificationModal}
            width={560}
            title="Propose a certification"
        >
            <LemonModal.Content>
                <div className="flex flex-col gap-4">
                    <LemonField.Pure label="Table or view">
                        <LemonSelect
                            value={selectedValue}
                            onChange={(value) => {
                                const selected = optionEntries.find((entry) => entry.value === value)
                                setNewCertificationForm({
                                    targetName: selected?.name ?? '',
                                    targetType: selected?.targetType ?? 'table',
                                })
                            }}
                            options={options}
                            loading={databaseLoading}
                            placeholder="Select a warehouse table or view"
                            data-attr="data-catalog-certification-target"
                        />
                    </LemonField.Pure>

                    <LemonField.Pure label="Notes">
                        <LemonTextArea
                            value={newCertificationForm.notes}
                            onChange={(notes) => setNewCertificationForm({ notes })}
                            placeholder="Why should the team trust this source?"
                            minRows={2}
                        />
                    </LemonField.Pure>
                </div>
            </LemonModal.Content>

            <LemonModal.Footer>
                <LemonButton type="secondary" onClick={closeNewCertificationModal} disabled={isCreatingCertification}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={createCertification}
                    loading={isCreatingCertification}
                    disabledReason={submitDisabledReason}
                    data-attr="data-catalog-create-certification-submit"
                >
                    Propose certification
                </LemonButton>
            </LemonModal.Footer>
        </LemonModal>
    )
}
