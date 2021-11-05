import React from 'react'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { Button, Tag } from 'antd'
import { Popup } from 'lib/components/Popup/Popup'
import PlusCircleOutlined from '@ant-design/icons/lib/icons/PlusCircleOutlined'

interface PersonPropertySelectProps {
    onChange: (names: string[]) => void
    selectedProperties: string[]
}

export const PersonPropertySelect = ({ onChange, selectedProperties }: PersonPropertySelectProps): JSX.Element => {
    const { open, toggle, hide } = usePopup()

    const handleChange = (name: string): void => {
        onChange(Array.from(new Set(selectedProperties.concat([name]))))
    }

    const handleRemove = (name: string): void => {
        onChange(selectedProperties.filter((p) => p !== name))
    }

    return (
        <div>
            <div>
                {selectedProperties.length > 0 &&
                    selectedProperties.map((name) => {
                        return (
                            <Tag
                                key={name}
                                closable
                                onClose={(): void => handleRemove(name)}
                                style={{
                                    margin: '0.25rem',
                                    padding: '0.25rem 0.5em',
                                    background: '#D9D9D9',
                                    border: '1px solid #D9D9D9',
                                    borderRadius: '40px',
                                }}
                            >
                                {name}
                            </Tag>
                        )
                    })}

                <Popup
                    visible={open}
                    overlay={
                        <TaxonomicFilter
                            onChange={(_, value) => {
                                handleChange(value as string)
                                hide()
                            }}
                            taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties]}
                        />
                    }
                >
                    {({ setRef }) => (
                        <Button
                            ref={setRef}
                            onClick={() => toggle()}
                            type="link"
                            className="new-prop-filter"
                            icon={<PlusCircleOutlined />}
                        >
                            Exclude person property
                        </Button>
                    )}
                </Popup>
            </div>
        </div>
    )
}

const popupLogic = {
    // eslint-disable-next-line @typescript-eslint/explicit-function-return-type
    toggle: (open: boolean) => !open,

    // eslint-disable-next-line @typescript-eslint/explicit-function-return-type
    hide: () => false,
}

// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
const usePopup = () => {
    const [open, setOpen] = React.useState<boolean>(false)

    return {
        open,
        toggle: () => setOpen(popupLogic.toggle(open)),
        hide: () => setOpen(popupLogic.hide()),
    }
}
