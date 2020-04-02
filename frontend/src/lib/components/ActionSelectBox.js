import React, { Component } from 'react'
import Select, { components } from 'react-select'
import { ActionSelectInfo } from '../../scenes/trends/ActionSelectInfo'
import { selectStyle } from '../utils'
import PropTypes from 'prop-types'

export class ActionSelectBox extends Component {
    constructor(props) {
        super(props)
        this.state = {
            entityType: 0
        }
    }
    actionContains(action, event) {
        return action.steps.filter(step => step.event == event).length > 0
    }

    Option = props => {
        return (
            <div
                onMouseOver={e =>
                    this.setState({
                        infoOpen: true,
                        infoBoundingRect: e.target.getBoundingClientRect(),
                        infoActionId: props.value,
                    })
                }
                onMouseOut={e => {
                    this.setState({ infoOpen: false })
                }}
            >
                <components.Option {...props} />
            </div>
        )
    }
    groupActions = actions => {
        let data = [
            { label: 'Autocapture', options: [] },
            { label: 'Event', options: [] },
            { label: 'Pageview', options: [] },
        ]
        actions.map(action => {
            let format = { label: action.name, value: action.id }
            if (this.actionContains(action, '$autocapture'))
                data[0].options.push(format)
            if (this.actionContains(action, '$pageview'))
                data[2].options.push(format)
            if (
                !this.actionContains(action, '$autocapture') &&
                !this.actionContains(action, '$pageview')
            )
                data[1].options.push(format)
        })
        return data
    }

    chooseEntityType = (type) => this.setState({entityType: type})

    render() {
        let {
            action,
            actions,
            onClose,
            onChange,
            defaultMenuIsOpen,
        } = this.props
        let {
            entityType
        } = this.state
        return (
            <div className="select-box" style={{padding: 0}}>
                <div style={{display: 'flex', flexDirection: 'row', height: '25px', borderBottom: "1px solid #cccccc"}}>
                    <div style={{backgroundColor: entityType == 0 ? 'white' : '#eeeeee', flex: 1, display:'flex', justifyContent: 'center'}} onClick={() => this.chooseEntityType(0)}>Action</div>
                    <div style={{backgroundColor: entityType == 1 ? 'white' : '#eeeeee', flex: 1, display:'flex', justifyContent: 'center'}} onClick={() => this.chooseEntityType(1)}>Event</div>
                </div>
                <div style={{padding: '1rem'}}>
                    {action.id && (
                        <a href={'/action/' + action.id} target="_blank">
                            Edit "{action.name}"{' '}
                            <i className="fi flaticon-export" />
                        </a>
                    )}
                    {this.state.infoOpen && (
                        <ActionSelectInfo
                            isOpen={this.state.infoOpen}
                            boundingRect={this.state.infoBoundingRect}
                            action={
                                actions.filter(
                                    a => a.id == this.state.infoActionId
                                )[0]
                            }
                        />
                    )}
                    <Select
                        onBlur={e => {
                            if (e.relatedTarget && e.relatedTarget.tagName == 'A')
                                return
                            this.setState({ infoOpen: false })
                            if (onClose) onClose()
                        }}
                        onChange={item => onChange(item.value)}
                        defaultMenuIsOpen={defaultMenuIsOpen}
                        autoFocus={true}
                        value={{
                            label: action.name,
                            value: action.id,
                        }}
                        className="select-box-select"
                        styles={selectStyle}
                        components={{ Option: this.Option }}
                        options={this.groupActions(actions)}
                    />
                </div>
            </div>
        )
    }
}
ActionSelectBox.propTypes = {
    onChange: PropTypes.func.isRequired,
    actions: PropTypes.array.isRequired,
    action: PropTypes.object.isRequired,
    onClose: PropTypes.func,
    defaultMenuIsOpen: PropTypes.bool,
}
