import { Skeleton } from 'antd'
import { useValues } from 'kea'
import React from 'react'
import { PageHeader } from '../../lib/components/PageHeader'
import { urls } from '../sceneLogic'
import { groupsLogic } from './groupsLogic'
import { Link } from 'lib/components/Link'

export function GroupTypes(): JSX.Element {
    const { groupTypes, groupTypesLoading } = useValues(groupsLogic)

    return (
        <div style={{ marginBottom: 128 }}>
            <PageHeader title="Groups" />
            {groupTypesLoading
                ? Array(5)
                      .fill(null)
                      .map((_, i) => <Skeleton key={i} active paragraph={false} />)
                : groupTypes.map(({ type_id, type_key }) => (
                      <Link key={type_id} to={urls.groups(type_key)}>
                          <div>
                              <code>{type_key}</code>
                          </div>
                      </Link>
                  ))}
        </div>
    )
}
