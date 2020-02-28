import React, { Component } from "react";
import ReactDOM from "react-dom";
import Simmer from 'simmerjs';
import root from 'react-shadow';
import { ActionEdit } from "../ActionEdit";
import Draggable from 'react-draggable';

window.simmer = new Simmer(window, {depth: 8});

let styles = `
    form { margin-bottom: 0 }
    .form-group { padding: 8px 12px; margin: 0 }
    .form-group.selected { background: rgba(0, 0, 0, 0.1)}
    .form-group:not(:last-child) {border-bottom: 1px solid rgba(0, 0, 0, 0.1) }
    .form-control { font-size: 13px }
    .react-draggable .drag-bar { cursor: grab; margin-bottom: 0.75rem; user-select: none }
    .react-draggable-dragging .drag-bar {cursor: grabbing !important }
    .logo { margin: -7px 15px 0 0; height: 35px }
    .drag-bar h3 { display: inline-block }
    .save-buttons {
        margin: 0 -12px;
        width: calc(100% + 24px);
    }
    .save-buttons .btn { border-radius: 0 }
    .action {
        background: rgba(0, 0, 0, 0.1);
        margin: 0 -12px;
        padding: 6px 12px;
        border-bottom: 1px solid rgba(0, 0, 0, 0.1);
        height: 32px;
    }
    .box {
        touch-action: none;
        position: fixed;
        top: 2rem;
        z-index: 999999999;
        padding: 12px 12px 0 12px;
        right: 2rem;
        overflow-y: scroll;
        width: 280px;
        color: #37352F;
        font-size: 13px;
        max-height: calc(100vh - 4rem);
        box-shadow: rgba(0, 0, 0, 0.4) 0px 0px 13px;
        border-radius: 10px;
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, "Fira Sans", "Droid Sans", "Helvetica Neue", sans-serif;

        /* effects when content is scrolling */
        background:
            linear-gradient(white 30%, rgba(255,255,255,0)),
            linear-gradient(rgba(255,255,255,0), white 70%) 0 100%,
            radial-gradient(50% 0, farthest-side, rgba(0,0,0,.4), rgba(0,0,0,0)),
            radial-gradient(50% 100%,farthest-side, rgba(0,0,0,.4), rgba(0,0,0,0)) 0 100%;
        background:
            linear-gradient(white 30%, rgba(255,255,255,0)),
            linear-gradient(rgba(255,255,255,0), white 70%) 0 100%,
            radial-gradient(farthest-side at 50% 0, rgba(0,0,0,.4), rgba(0,0,0,0)),
            radial-gradient(farthest-side at 50% 100%, rgba(0,0,0,.4), rgba(0,0,0,0)) 0 100%;
        background-repeat: no-repeat;
        background-color: #f8f9fa;
        background-size: 100% 70px, 100% 70px, 100% 24px, 100% 24px;
        /* Opera doesn't support this in the shorthand */
        background-attachment: local, local, scroll, scroll;
    }

    /* form fields */
    label { margin-bottom: 8px }
    input.form-control {
        padding: 8px;
        height: calc(1.5rem + 4px);
    }
`;
class App extends Component {
    constructor(props) {
        super(props)

        this.state = {
            actions: JSON.parse(sessionStorage.getItem('editorActions')) || [],
            openActionId: false
        };
        if(props.actionId) {
            this.state.actions = [{'id': props.actionId}];
            this.state.openActionId = props.actionId;
        } else {
            if(this.state.actions.filter((action) => action.id === false).length == 0) this.state.actions.push({'id': false})
        }
        this.onActionSave = this.onActionSave.bind(this);
    }
    onActionSave(action, isNew, createNew) {
        let { actions, openActionId } = this.state;
        if(isNew) {
            actions = actions.map((a) => !a.id ? action : a)
            openActionId = action.id;
        } else {
            actions = actions.map((a) => a.id == action.id ? action : a)
        }
        if(createNew) {
            actions.push({'id': false});
            openActionId = false;
        } else {
            window.location.href = this.props.apiURL + 'action/' + action.id;
            sessionStorage.setItem('editorActions', "[]");
            return sessionStorage.setItem('editorParams', "");
        }
        this.setState({actions, openActionId});
        sessionStorage.setItem('editorActions', JSON.stringify(actions))
    }
    render() {
        let { actions, openActionId } = this.state;
        return <root.div>
            <link href={this.props.apiURL + "static/style.css"} rel="stylesheet" crossorigin="anonymous" />
            <style>{styles}</style>
            <Draggable handle='.drag-bar'>
                <div className='box'>
                    <div className='drag-bar'>
                        <img className="logo" src={this.props.apiURL + "static/posthog-logo.png"} />
                        <h3>PostHog</h3><br />
                    </div>
                    {actions.map((action, index) => (action.id == openActionId) ? <div>
                        <div className='action'>
                            {!action.id && 'New action'}
                            {action.id && <a
                                onClick={(e) => {
                                    e.preventDefault();
                                    this.setState({openActionId: false})
                                }}
                                href='#'
                                className='float-right'>
                                collapse
                            </a>}
                        </div>
                        <ActionEdit
                            apiURL={this.props.apiURL}
                            temporaryToken={this.props.temporaryToken}
                            actionId={action.id}
                            simmer={window.simmer}
                            onSave={this.onActionSave}
                            showNewActionButton={index == actions.length -1}
                            isEditor={true} />
                        </div> :
                        <div className='action'>
                            {action.id ? action.name : 'New action'}
                            <a
                                onClick={(e) => {
                                    e.preventDefault();
                                    this.setState({openActionId: action.id})
                                }}
                                href='#'
                                className='float-right'>
                                edit
                            </a>
                        </div>
                    )}
                </div>
            </Draggable>
        </root.div>
    }
}

window.ph_load_editor = function(editorParams) {
    let container = document.createElement('div');
    document.body.appendChild(container);

    ReactDOM.render(<App apiURL={editorParams.apiURL} temporaryToken={editorParams.temporaryToken} actionId={editorParams.actionId} />, container);
}
