import { useActions, useValues } from 'kea'
import { Drawer } from 'lib/components/Drawer'
import React from 'react'
import { definitionsLogic } from './definitionsLogic'
import Title from 'antd/es/typography/Title'
import './VolumeTable.scss'
import { Collapse, Input, Select } from 'antd'
import { ObjectTags } from 'lib/components/ObjectTags'
import { UserBasicType } from '~/types'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { ProfilePicture } from '~/layout/navigation/TopNavigation'

export function DefinitionDrawer(): JSX.Element {
    const { drawerState, definition, tags, definitionLoading } = useValues(definitionsLogic)
    const { closeDrawer, saveNewTag, deleteTag } = useActions(definitionsLogic)
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
                                        {/* <ObjectTags tags={definition.tags}/> */}
                                        <ObjectTags
                                            tags={tags}
                                            onTagSave={saveNewTag}
                                            onTagDelete={deleteTag}
                                            saving={definitionLoading}
                                        />
                                        <DefinitionOwner owner={definition.owner}/>
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
    return(
        <>
            <div style={{flexDirection: 'column', minWidth: 300}}>
                <Title level={5}>Description</Title>
                <Input.TextArea style={{minHeight: 80}}/>
            </div>
        </>
    )
}

export function DefinitionOwner({ owner }: { owner: UserBasicType }): JSX.Element {
    const { members } = useValues(membersLogic)
    return(
        <div style={{paddingTop: 16}}>
            <Title level={5}>Owner</Title>
            <Select defaultValue={owner?.first_name} style={{ width: 120 }}>
                {members.map((member) => (
                    <Select.Option key={member.user_id} value={member.user_id}>
                        <ProfilePicture name={member.user_first_name} email={member.user_email} small={true}/>
                        {member.user_first_name}
                    </Select.Option>
                ))}
            </Select>
        </div>
    )
}