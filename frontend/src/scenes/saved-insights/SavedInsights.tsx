import { Table } from 'antd'
import { ColumnType } from 'antd/lib/table';
import { useActions, useValues } from 'kea';
import { Link } from 'lib/components/Link';
import { ObjectTags } from 'lib/components/ObjectTags';
import { createdByColumn } from 'lib/components/Table/Table';
import { humanFriendlyDetailedTime } from 'lib/utils';
import React, { useEffect, useState } from 'react'
import { userLogic } from 'scenes/userLogic';
import { DashboardItemType } from '~/types';
import { savedInsightsLogic } from './savedInsightsLogic';

export function SavedInsights(): JSX.Element {
    const { loadInsights } = useActions(savedInsightsLogic)
    const { insights } = useValues(savedInsightsLogic)
    const { hasDashboardCollaboration } = useValues(userLogic)
    const [displayedColumns, setDisplayedColumns] = useState([] as ColumnType<DashboardItemType>[])

    useEffect(() => {
        loadInsights()
    }, [])

    useEffect(() => {
        if (!hasDashboardCollaboration) {
            setDisplayedColumns(
                columns.filter((col) => !col.dataIndex || !['description', 'tags'].includes(col.dataIndex.toString()))
            )
        } else {
            setDisplayedColumns(columns)
        }
    }, [hasDashboardCollaboration])

    const columns = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: function renderName (name: string, { short_id }: {short_id: string}) { return <Link to={`/i/${short_id}`}>{name || 'No name set'}</Link> }
          },
          {
            title: 'Description',
            dataIndex: 'description',
            key: 'description',
            render: function renderDescription(description: string) { return <span>{description}</span> }
          },
          {
              title: 'Tags',
              dataIndex: 'tags',
              key: 'tags',
              render: function renderTags(tags: string[]) { return <ObjectTags tags={tags} staticOnly/> }
          },      
          {
              title: 'Last modified',
              dataIndex: 'updated_at',
              key: 'updated_at',
              render: function renderLastModified(updated_at: string) { return <span>{humanFriendlyDetailedTime(updated_at)}</span> }
          },
        createdByColumn(insights) as ColumnType<DashboardItemType>,
    ]
    
    return (
        <Table 
            columns={displayedColumns}
            dataSource={insights}
        />
    )
}

