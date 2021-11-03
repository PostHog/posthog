import React from 'react'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { Button, Row } from 'antd'
import { Popup } from 'lib/components/Popup/Popup'
import PlusCircleOutlined from '@ant-design/icons/lib/icons/PlusCircleOutlined'
import { CloseButton } from 'lib/components/CloseButton'

interface EventSelectProps {
    onChange: (names: string[]) => void
    selectedEvents: string[]
}

export const EventSelect = ({ onChange, selectedEvents: selectedEvents }: EventSelectProps): JSX.Element => {
    const { open, toggle, hide } = usePopup()

    const handleChange = (name: string): void => {
        onChange(Array.from(new Set(selectedEvents.concat([name]))))
    }

    const handleRemove = (name: string): void => {
        onChange(selectedEvents.filter((p) => p !== name))
    }

    return (
        <div className="mb">
            {selectedEvents.length > 0 &&
                selectedEvents.map((name) => {
                    return (
                        <Row
                            key={name}
                            align="middle"
                            className="property-filter-row mt-05 mb-05"
                            style={{
                                width: '100%',
                                margin: '0.25rem 0',
                                padding: '0.25rem 0',
                            }}
                        >
                            <Button type="primary" shape="round">
                                {name}
                            </Button>{' '}
                            <CloseButton
                                className="ml-1"
                                onClick={() => handleRemove(name)}
                                style={{ cursor: 'pointer', float: 'none', marginLeft: 5 }}
                            />
                        </Row>
                    )
                })}
            <Row>
                <Popup
                    visible={open}
                    overlay={
                        <TaxonomicFilter
                            onChange={(_, value) => {
                                handleChange(value as string)
                                hide()
                            }}
                            taxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
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
                            Exclude event
                        </Button>
                    )}
                </Popup>
            </Row>
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
