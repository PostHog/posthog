import { ReactNode } from 'react'

import type { BlockPropsRecord } from '../../../editing/blockLibrary/blockDefinitions'
import { builderSql } from '../../../editing/blockLibrary/blockSql'
import { InspectorField } from './InspectorField'
import { BlockPropsChange } from './inspectorValues'
import { Segmented } from './Segmented'
import { SqlField } from './SqlField'
import { TitleField } from './TitleField'

/** Switches a data block between its builder settings and a HogQL query written from them. */
export function QueryModeFields({
    type,
    props,
    onChange,
    children,
}: {
    type: string
    props: BlockPropsRecord
    onChange: BlockPropsChange
    children: ReactNode
}): JSX.Element {
    const sql = typeof props.sql === 'string' ? props.sql : null
    return (
        <>
            <InspectorField label="Data">
                <Segmented
                    value={sql === null ? 'builder' : 'sql'}
                    ariaLabel="Data"
                    options={[
                        { value: 'builder', label: 'Builder' },
                        { value: 'sql', label: 'SQL' },
                    ]}
                    onChange={(mode) =>
                        onChange(
                            mode === 'sql' ? { ...props, sql: builderSql(type, props) } : { ...props, sql: undefined }
                        )
                    }
                />
            </InspectorField>
            {sql === null ? (
                children
            ) : (
                <>
                    <TitleField props={props} onChange={onChange} />
                    <SqlField type={type} sql={sql} onCommit={(next) => onChange({ ...props, sql: next })} />
                </>
            )}
        </>
    )
}
