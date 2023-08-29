import { LemonButton, LemonDivider, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { IconDelete, IconSwapHoriz } from 'lib/lemon-ui/icons'
import { viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'
import { Form, Field } from 'kea-forms'
import { useActions, useValues } from 'kea'

export function ViewLinkModal(): JSX.Element {
    const { viewOptions, toJoinKeyOptions, selectedView, selectedTable, isFieldModalOpen, fromJoinKeyOptions } =
        useValues(viewLinkLogic)
    const { selectView, toggleFieldModal } = useActions(viewLinkLogic)

    return (
        <LemonModal
            title="Link view to table"
            description={
                <span>
                    Define a join between the table and view. <b>All</b> fields from the view will be accessible in
                    queries at the top level without needing to explicitly join the view.
                </span>
            }
            isOpen={isFieldModalOpen}
            onClose={toggleFieldModal}
            width={600}
        >
            <Form logic={viewLinkLogic} formKey="viewLink" enableFormOnSubmit>
                <div className="flex flex-col w-full justify-between items-center">
                    <div className="flex flex-row w-full justify-between">
                        <div className="flex flex-col">
                            <span className="l4">Table</span>
                            {selectedTable ? selectedTable.name : ''}
                        </div>
                        <div className="w-50">
                            <span className="l4">View</span>
                            <Field name="saved_query_id">
                                <LemonSelect
                                    fullWidth
                                    options={viewOptions}
                                    onSelect={selectView}
                                    placeholder="Select a view"
                                />
                            </Field>
                        </div>
                    </div>
                    <div className="mt-3 flex flex-row justify-between items-center w-full">
                        <div className="w-50">
                            <span className="l4">Table Key</span>
                            <Field name="from_join_key">
                                <LemonSelect fullWidth options={fromJoinKeyOptions} placeholder="Select a key" />
                            </Field>
                        </div>
                        <div className="mt-5">
                            <IconSwapHoriz />
                        </div>
                        <div className="w-50">
                            <span className="l4">View Key</span>
                            <Field name="to_join_key">
                                <LemonSelect
                                    fullWidth
                                    disabledReason={selectedView ? '' : 'Select a view to choose join key'}
                                    options={toJoinKeyOptions}
                                    placeholder="Select a key"
                                />
                            </Field>
                        </div>
                    </div>
                </div>
                <LemonDivider className="mt-4 mb-4" />
                <div className="flex flex-row justify-end w-full">
                    <LemonButton className="mr-3" type="secondary" onClick={toggleFieldModal}>
                        Close
                    </LemonButton>
                    <LemonButton type="primary" htmlType="submit">
                        Save
                    </LemonButton>
                </div>
            </Form>
        </LemonModal>
    )
}

interface ViewLinkDeleteButtonProps {
    table: string
    column: string
}

export function ViewLinkDeleteButton({ table, column }: ViewLinkDeleteButtonProps): JSX.Element {
    const { deleteViewLink } = useActions(viewLinkLogic)

    return (
        <LemonButton
            icon={<IconDelete />}
            onClick={() => deleteViewLink(table, column)}
            tooltip={'Remove view association'}
            tooltipPlacement="bottomLeft"
            status="primary-alt"
            type="tertiary"
            size="small"
        />
    )
}
