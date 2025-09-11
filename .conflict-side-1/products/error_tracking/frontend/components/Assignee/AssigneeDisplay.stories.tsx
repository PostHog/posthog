import { Meta } from '@storybook/react'

import { AssigneeDisplay, AssigneeIconDisplayProps } from './AssigneeDisplay'

const meta: Meta = {
    title: 'ErrorTracking/AssigneeDisplay',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
    args: {
        sizes: ['xsmall', 'small', 'medium', 'large'],
    },
}

export default meta

type SizedComponentProps = {
    sizes: AssigneeIconDisplayProps['size'][]
}

export const UnassignedDisplays = ({ sizes }: SizedComponentProps): JSX.Element => {
    return (
        <div className="space-y-4">
            {sizes.map((size) => (
                <AssigneeDisplay key={size} size={size} assignee={null} />
            ))}
        </div>
    )
}

export const UserDisplays = ({ sizes }: SizedComponentProps): JSX.Element => {
    return (
        <div className="space-y-4">
            {sizes.map((size) => (
                <AssigneeDisplay
                    key={size}
                    size={size}
                    assignee={{
                        id: 1,
                        type: 'user',
                        user: {
                            id: 1,
                            uuid: '123e4567-e89b-12d3-a456-426614174000',
                            distinct_id: '123e4567-e89b-12d3-a456-426614174000',
                            first_name: 'John',
                            last_name: 'Doe',
                            email: 'john.doe@gmail.com',
                        },
                    }}
                />
            ))}
        </div>
    )
}

export const GroupDisplays = ({ sizes }: SizedComponentProps): JSX.Element => {
    return (
        <div className="space-y-4">
            {sizes.map((size) => (
                <AssigneeDisplay
                    key={size}
                    size={size}
                    assignee={{
                        id: '123',
                        type: 'role',
                        role: {
                            id: '123',
                            name: 'Role Name',
                            feature_flags_access_level: 37,
                            members: [],
                            created_at: '2021-08-02 12:34:56',
                            created_by: null,
                        },
                    }}
                />
            ))}
        </div>
    )
}

export const AllDisplays = ({ sizes }: SizedComponentProps): JSX.Element => {
    return (
        <div className="flex gap-4 justify-start items-start">
            <UnassignedDisplays sizes={sizes} />
            <UserDisplays sizes={sizes} />
            <GroupDisplays sizes={sizes} />
        </div>
    )
}
