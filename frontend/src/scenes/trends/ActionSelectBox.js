import React, { Component } from 'react'
import Select, { components } from 'react-select'
import { ActionSelectInfo } from './ActionSelectInfo'
import { selectStyle } from '../../lib/utils'
import PropTypes from 'prop-types'

export class ActionSelectBox extends Component {
    constructor(props) {
        super(props)
        this.state = {}
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
    render() {
        let { action, actions, onClose, onChange } = this.props
        return (
            <div className="select-box">
                {action.id && (
                    <a href={'/action/' + action.id} target="_blank">
                        Edit "{action.name}"{' '}
                        <i className="fi flaticon-export" />
                    </a>
                )}
                <ActionSelectInfo
                    isOpen={this.state.infoOpen}
                    boundingRect={this.state.infoBoundingRect}
                    action={
                        actions.filter(a => a.id == this.state.infoActionId)[0]
                    }
                />
                <Select
                    onBlur={e => {
                        if (e.relatedTarget && e.relatedTarget.tagName == 'A')
                            return
                        onClose()
                    }}
                    onChange={item => onChange(item.value)}
                    defaultMenuIsOpen={true}
                    autoFocus={true}
                    // menuIsOpen={true}
                    styles={selectStyle}
                    components={{ Option: this.Option }}
                    options={this.groupActions(actions)}
                />
            </div>
        )
    }
}
ActionSelectBox.propTypes = {
    actionFilters: PropTypes.array.isRequired,
    onChange: PropTypes.func.isRequired,
    actions: PropTypes.array.isRequired,
    action: PropTypes.object.isRequired,
}
