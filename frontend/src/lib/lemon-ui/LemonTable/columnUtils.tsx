import { TZLabel } from 'lib/components/TZLabel' // TODO: Bring this into Lemon UI
import { ProfilePicture } from '../ProfilePicture'
import { LemonTableColumn } from './types'
import { UserBasicType } from '~/types'

function dateRenderer(date?: string | null): JSX.Element {
    return date ? (
        <div className="whitespace-nowrap text-right">
            <TZLabel time={date} />
        </div>
    ) : (
        <span className="text-muted">—</span>
    )
}

function userRenderer(user?: UserBasicType | null): JSX.Element {
    return <div>{user && <ProfilePicture name={user.first_name} email={user.email} size="md" showName />}</div>
}

export function createdAtColumn<T extends { created_at?: string | null }>(): LemonTableColumn<T, 'created_at'> {
    return {
        title: 'Created',
        dataIndex: 'created_at',
        render: dateRenderer,
        align: 'right',
        sorter: (a, b) => (new Date(a.created_at || 0) > new Date(b.created_at || 0) ? 1 : -1),
    }
}

export function updatedAtColumn<T extends { updated_at?: string | null }>(): LemonTableColumn<T, 'updated_at'> {
    return {
        title: 'Updated',
        dataIndex: 'updated_at',
        render: dateRenderer,
        align: 'right',
        sorter: (a, b) => (new Date(a.updated_at || 0) > new Date(b.updated_at || 0) ? 1 : -1),
    }
}

export function createdByColumn<T extends { created_by?: UserBasicType | null }>(): LemonTableColumn<T, 'created_by'> {
    return {
        title: 'Created by',
        dataIndex: 'created_by',
        render: userRenderer,
        sorter: (a, b) =>
            (a.created_by?.first_name || a.created_by?.email || '').localeCompare(
                b.created_by?.first_name || b.created_by?.email || ''
            ),
    }
}

export function updatedByColumn<T extends { updated_by?: UserBasicType | null }>(): LemonTableColumn<T, 'updated_by'> {
    return {
        title: 'Updated by',
        dataIndex: 'updated_by',
        render: userRenderer,
        sorter: (a, b) =>
            (a.updated_by?.first_name || a.updated_by?.email || '').localeCompare(
                b.updated_by?.first_name || b.updated_by?.email || ''
            ),
    }
}
