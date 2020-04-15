import React from 'react'
import { PropertyFilter } from './PropertyFilter'
import { Button } from 'antd'
import { useValues, useActions } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'

export function PropertyFilters({ endpoint, propertyFilters, className, style, onChange, pageKey }) {
    const { filters } = useValues(propertyFilterLogic({ propertyFilters, endpoint, onChange, pageKey }))
    const { newFilter } = useActions(propertyFilterLogic({ propertyFilters, endpoint, onChange, pageKey }))

    return (
        <div
            className={className || 'col-8'}
            style={{
                marginBottom: '2rem',
                padding: 0,
                style,
            }}
        >
            {filters &&
                filters.map((item, index) => (
                    <span>
                        <PropertyFilter key={index} index={index} endpoint={endpoint || 'event'} onChange={onChange} />
                        {index != filters.length - 1 && (
                            <div className="row">
                                <div className="secondary offset-4 col-2" style={{ textAlign: 'center' }}>
                                    AND
                                </div>
                            </div>
                        )}
                    </span>
                ))}
            <Button type="primary" onClick={() => newFilter()} style={{ marginTop: '0.5rem' }}>
                {filters.length == 0 ? 'Filter by property' : 'Add another filter'}
            </Button>
        </div>
    )
}
