import React from 'react'
import { Select } from 'antd'
import { useValues, useActions } from 'kea'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { UserBasicType } from '~/types'
import { definitionDrawerLogic } from './definitionDrawerLogic'
import { Owner } from '../Owner'

export function DefinitionOwnerDropdown({ owner }: { owner: UserBasicType | null }): JSX.Element {
    const { members } = useValues(membersLogic)
    const { changeOwner } = useActions(definitionDrawerLogic)

    return (
        <div style={{ paddingTop: 16 }}>
            <h4 className="l4">Owner</h4>
            <Select
                className="owner-select"
                placeholder={<Owner user={owner} />}
                style={{ minWidth: 200 }}
                dropdownClassName="owner-option"
                onChange={(val) => {
                    const newOwner = members.find((mem) => mem.user.id === val)?.user
                    if (newOwner) {
                        changeOwner(newOwner)
                    }
                }}
            >
                {members.map((member) => (
                    <Select.Option key={member.user.id} value={member.user.id}>
                        <Owner user={member.user} />
                    </Select.Option>
                ))}
            </Select>
        </div>
    )
}
