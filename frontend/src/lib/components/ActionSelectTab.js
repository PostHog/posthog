import React from 'react'
import { capitalizeFirstLetter } from '~/lib/utils'

export function ActionSelectTab({ entityType, chooseEntityType, allTypes }) {
    return (
        <div style={{ display: 'flex', flexDirection: 'row', height: '25px', borderBottom: '1px solid #cccccc' }}>
            {allTypes.map((type, index) => (
                <div
                    key={index}
                    style={{
                        backgroundColor: entityType == type ? '#eeeeee' : 'white',
                        flex: 1,
                        display: 'flex',
                        justifyContent: 'center',
                        borderTopLeftRadius: index == 0 ? '5px' : '0px',
                        borderTopRightRadius: index == allTypes.length - 1 ? '5px' : '0px',
                        cursor: 'pointer',
                    }}
                    onClick={() => chooseEntityType(type)}
                >
                    {capitalizeFirstLetter(type)}
                </div>
            ))}
        </div>
    )
}
