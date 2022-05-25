import React from 'react'

export interface FormErrorsProps {
    errors: Record<string, any>
}
export function FormErrors({ errors }: FormErrorsProps): JSX.Element {
    return (
        <>
            {Object.entries(errors)
                .filter(([, error]) => !!error)
                .map(([key, error]) => (
                    <div key={key}>
                        <strong>{key}: </strong>
                        <span>{typeof error === 'object' ? <FormErrors errors={error} /> : String(error)}</span>
                    </div>
                ))}
        </>
    )
}
