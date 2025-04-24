import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { saveUnderLogic, SaveUnderLogicProps } from 'lib/components/SaveUnder/saveUnderLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'

export function SaveUnderModal(): JSX.Element {
    const { isOpen } = useValues(saveUnderLogic)
    const { closeModal, submitSaveUnder } = useActions(saveUnderLogic)

    return (
        <LemonModal
            onClose={() => {
                closeModal()
            }}
            isOpen={isOpen}
            title="Save to folder"
            footer={
                <>
                    <div className="flex-1">
                        <LemonButton type="primary" onClick={submitSaveUnder}>
                            Save
                        </LemonButton>
                    </div>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Close
                    </LemonButton>
                </>
            }
        >
            <div className="deprecated-space-y-2 w-192 max-w-full">
                <Form logic={saveUnderLogic} formKey="saveUnder">
                    <LemonField name="name">
                        <LemonInput data-attr="save-under-name" type="text" fullWidth placeholder="Name" />
                    </LemonField>
                    <div className="text-secondary">This insight is referenced</div>
                    {/*<div className="min-h-[420px]">*/}
                    {/*    <AutoSizer>*/}
                    {/*        {({ height, width }) => (*/}
                    {/*            <List*/}
                    {/*                width={width}*/}
                    {/*                height={height}*/}
                    {/*                rowCount={orderedDashboards.length}*/}
                    {/*                overscanRowCount={100}*/}
                    {/*                rowHeight={40}*/}
                    {/*                rowRenderer={renderItem}*/}
                    {/*                scrollToIndex={scrollIndex}*/}
                    {/*            />*/}
                    {/*        )}*/}
                    {/*    </AutoSizer>*/}
                    {/*</div>*/}
                </Form>
            </div>
        </LemonModal>
    )
}

export function SaveUnder(props: SaveUnderLogicProps): JSX.Element {
    const { openModal } = useActions(saveUnderLogic(props))
    const { path, objectRef } = props
    const pathParts = splitPath(path)

    return (
        <BindLogic logic={saveUnderLogic} props={props}>
            <div className="text-xs font-normal text-center mr-1">
                <div className="text-muted">{!objectRef ? 'Save' : 'Saved'} under</div>
                <Tooltip title={path}>
                    <div className="underline cursor-pointer" onClick={openModal}>
                        {pathParts.length > 0 ? pathParts[pathParts.length - 1] || 'Unfiled' : 'Unfiled'}
                    </div>
                </Tooltip>
                <SaveUnderModal />
            </div>
        </BindLogic>
    )
}
