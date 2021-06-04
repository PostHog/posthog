import { useActions, useValues } from 'kea'
import { Drawer } from 'lib/components/Drawer'
import React from 'react'
import { definitionDrawerLogic } from './definitionDrawerLogic'
import Title from 'antd/es/typography/Title'
import './VolumeTable.scss'
import { Button, Collapse, Input, Select } from 'antd'
import { ObjectTags } from 'lib/components/ObjectTags'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { Owner } from './VolumeTable'
import { humanFriendlyDetailedTime } from 'lib/utils'

export function DefinitionDrawer(): JSX.Element {
    const { drawerState, definition, definitionLoading } = useValues(definitionDrawerLogic)
    const { closeDrawer, saveNewTag, deleteTag } = useActions(definitionDrawerLogic)
    const { Panel } = Collapse;

    return(
        <>
            {definition && (
                <div className="definition-drawer">
                    <Drawer
                        placement="right"
                        headerStyle={{paddingBottom: 0}}
                        title={<Title level={3}>{definition.name}</Title>}
                        visible={drawerState}
                        onClose={closeDrawer}
                        width={'60vw'}
                        bodyStyle={{padding: 14, paddingTop: 0}}
                    >
                        <Collapse defaultActiveKey={['1']} expandIconPosition="right" ghost>
                            <Panel header="General" key="1" style={{fontSize: 18, fontWeight: 600}}>
                                <div style={{display: 'flex', flexDirection: 'row', paddingTop: 0}}>
                                    <DefinitionDescription />
                                    <div style={{flexDirection: 'column', paddingLeft: 14}}>
                                        <Title level={5}>Tags</Title>
                                        <ObjectTags
                                            tags={definition.tags}
                                            onTagSave={saveNewTag}
                                            onTagDelete={deleteTag}
                                            saving={definitionLoading}
                                        />
                                        <DefinitionOwner ownerId={definition.owner}/>
                                    </div>
                                </div>
                                <div className="detail-status">
                                    <div>
                                        <Title level={5}>First seen</Title>
                                        {/* <span></span> */}
                                    </div>
                                    <div>
                                        <Title level={5}>Last seen</Title>
                                        {/* <span></span> */}
                                    </div>
                                    <div>
                                        <Title level={5}>Last modified</Title>
                                        <span>{ humanFriendlyDetailedTime(definition.updated_at) }</span>
                                    </div>
                                    <div>
                                        <Title level={5}>Last modified by</Title>
                                        <span>{ definition.updated_by?.first_name }</span>
                                    </div>
                                </div>
                            </Panel>
                        </Collapse>
                    </Drawer>
                </div>
            )}
        </>
    )
}

export function DefinitionDescription(): JSX.Element {
    const { description, editing } = useValues(definitionDrawerLogic)
    const { setDescription, saveDescription, cancelDescription, setDescriptionEditing } = useActions(definitionDrawerLogic)

    return(
        <>
            <div style={{flexDirection: 'column', minWidth: 300}}>
                <Title level={5}>Description</Title>
                <Input.TextArea
                    style={{minHeight: 108}}
                    placeholder="Add description"
                    value={description || ''}
                    onChange={(e) => {
                        setDescription(e.target.value)
                        setDescriptionEditing(true)
                    }}
                    onKeyDown={(e) => e.key === 'Enter' && saveDescription() }
                />
                {editing && (
                    <>
                        <Button
                            style={{ marginRight: 8 }}
                            size="small"
                            type="primary"
                            onClick={() => {
                                setDescriptionEditing(false)
                                saveDescription()
                            }}
                        >
                            Save
                        </Button>
                        <Button
                            onClick={cancelDescription}
                            size="small"
                        >
                            Cancel
                        </Button>
                    </>
                )}
            </div>
        </>
    )
}

export function DefinitionOwner({ ownerId }: { ownerId: number }): JSX.Element {
    const { members } = useValues(membersLogic)
    const { changeOwner } = useActions(definitionDrawerLogic)

    return(
        <div style={{paddingTop: 16}}>
            <Title level={5}>Owner</Title>
            <Select
                className="owner-select"
                placeholder={<Owner ownerId={ownerId} />}
                style={{ minWidth: 200 }}
                dropdownClassName="owner-option"
                onChange={(val) => changeOwner(val)}
            >
                {members.map((member) => (
                    <Select.Option key={member.user_id} value={member.user.id}>
                        <Owner user={member.user} />
                    </Select.Option>
                ))}
            </Select>
        </div>
    )
}

