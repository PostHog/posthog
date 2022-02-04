import React from 'react'
import { Select } from 'antd'
import { useValues, useActions } from 'kea'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { UserBasicType } from '~/types'
import { definitionDrawerLogic } from './definitionDrawerLogic'
import { Owner } from '../Owner'
import clsx from 'clsx'

export function DefinitionOwnerDropdown({
    owner,
    className,
}: {
    owner: UserBasicType | null
    className?: string
}): JSX.Element {
    const { members } = useValues(membersLogic)
    const { changeOwner } = useActions(definitionDrawerLogic)

    return (
        <Select
            className={clsx('owner-select', className)}
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
    )
}
