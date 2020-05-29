import React, { Component } from 'react'
import { ActionEdit } from 'scenes/actions/ActionEdit'

export class ToolBar extends Component {
    constructor(props) {
        super(props)

        this.state = {
            actions: JSON.parse(sessionStorage.getItem('editorActions')) || [],
            openActionId: false,
        }
        if (props.actionId) {
            this.state.actions = [{ id: props.actionId }]
            this.state.openActionId = props.actionId
        } else {
            if (this.state.actions.filter(action => action.id === false).length === 0)
                this.state.actions.push({ id: false })
        }
    }
    onActionSave = (action, isNew, createNew) => {
        let { actions } = this.state
        if (isNew) {
            actions = actions.map(a => (!a.id ? action : a))
        } else {
            actions = actions.map(a => (a.id === action.id ? action : a))
        }
        if (createNew) {
            actions.push({ id: false })
        }
        this.setState({ actions, openActionId: false })
        sessionStorage.setItem('editorActions', JSON.stringify(actions))
    }
    render() {
        let { actions, openActionId } = this.state
        return (
            <>
                <div className="drag-bar">
                    <img alt="PostHog" className="logo" src={this.props.apiURL + 'static/posthog-logo.png'} />
                    <h3>PostHog</h3>
                    <br />
                </div>
                {actions.map((action, index) =>
                    action.id === openActionId ? (
                        <div>
                            <div className="action">
                                {!action.id && 'New action'}
                                {action.id && (
                                    <a
                                        onClick={e => {
                                            e.preventDefault()
                                            this.setState({
                                                openActionId: false,
                                            })
                                        }}
                                        href="#"
                                        className="float-right"
                                    >
                                        collapse
                                    </a>
                                )}
                            </div>
                            <ActionEdit
                                apiURL={this.props.apiURL}
                                temporaryToken={this.props.temporaryToken}
                                actionId={action.id}
                                simmer={window.simmer}
                                onSave={this.onActionSave}
                                showNewActionButton={index === actions.length - 1}
                                isEditor={true}
                            />
                        </div>
                    ) : (
                        <div className="action">
                            {action.id ? action.name : 'New action'}
                            <a
                                onClick={e => {
                                    e.preventDefault()
                                    this.setState({
                                        openActionId: action.id,
                                    })
                                }}
                                href="#"
                                className="float-right"
                            >
                                Edit
                            </a>
                            {'  '}
                            {action.id && (
                                <a
                                    href={this.props.apiURL + 'action/' + action.id}
                                    onClick={() => sessionStorage.setItem('editorActions', '[]')}
                                    className="float-right mr-1"
                                >
                                    View
                                </a>
                            )}
                        </div>
                    )
                )}
            </>
        )
    }
}
