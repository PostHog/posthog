import { IconErrorOutline } from 'lib/components/icons'
import React from 'react'
import { LemonLabel } from '../components/LemonLabel/LemonLabel'

export interface FieldV2Props {
    /** The name of the form field */
    name?: string | number
    /** The label name to be displayed */
    label?: string | JSX.Element | null
    /** Info tooltip to be displayed next to the label */
    info?: string | JSX.Element
    /** Help text to be shown directly beneath the input */
    help?: string | JSX.Element
    /** Error message to be displayed */
    error?: string
    children?: React.ReactNode
}

export const FieldV2 = ({ label, info, error, help, children }: FieldV2Props): JSX.Element => {
    return (
        <div className="flex flex-col gap-2">
            {label ? <LemonLabel info={info}>{label}</LemonLabel> : null}
            {children}
            {help ? <div className="text-muted">{help}</div> : null}
            {error ? (
                <div className="text-danger flex items-center gap-1">
                    <IconErrorOutline className="text-xl" /> {error}
                </div>
            ) : null}
        </div>
    )
    // /** Drop-in replacement antd template for kea forms */
    // const template: FieldV2Props['template'] = noStyle
    //     ? ({ kids }) => <>{kids}</>
    //     : ({ label, kids, hint, error }) => {
    //           return (
    //               <div
    //                   className={clsx(
    //                       'ant-row',
    //                       'ant-form-item',
    //                       help || hint || error ? 'ant-form-item-with-help' : '',
    //                       error ? `ant-form-item-has-error` : '',
    //                       className
    //                   )}
    //                   style={style}
    //               >
    //                   {label ? (
    //                       <div className="ant-col ant-form-item-label">
    //                           <label htmlFor={String(name)} title={typeof label === 'string' ? label : undefined}>
    //                               {showOptional ? (
    //                                   <>
    //                                       {label}
    //                                       {showOptional ? (
    //                                           <span className="ant-form-item-optional" title="">
    //                                               (optional)
    //                                           </span>
    //                                       ) : null}
    //                                   </>
    //                               ) : (
    //                                   label
    //                               )}
    //                           </label>
    //                       </div>
    //                   ) : null}
    //                   <div className="ant-col ant-form-item-control">
    //                       <div className="ant-form-item-control-input">
    //                           <div className="ant-form-item-control-input-content">{kids}</div>
    //                       </div>
    //                       {hint || error || help ? (
    //                           <div className="ant-form-item-explain ant-form-item-explain-connected">
    //                               {error ? (
    //                                   <div role="alert" className="ant-form-item-explain-error">
    //                                       {error}
    //                                   </div>
    //                               ) : null}
    //                               {hint ? (
    //                                   <div role="alert" className="ant-form-item-explain-warning">
    //                                       {hint}
    //                                   </div>
    //                               ) : null}
    //                               {help ? <div className="ant-form-item-explain">{help}</div> : null}
    //                           </div>
    //                       ) : null}
    //                   </div>
    //               </div>
    //           )
    //       }

    // return <KeaField {...keaFieldProps} name={name} template={template} />
}
