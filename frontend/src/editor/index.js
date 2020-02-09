import React, { Component } from "react";
import ReactDOM from "react-dom";
import Simmer from 'simmerjs';
import root from 'react-shadow';
import { ActionEdit } from "../ActionEdit";
import Draggable from 'react-draggable';

window.simmer = new Simmer(window, {depth: 8});

let styles = `
    .form-group { padding: 1rem 12px;margin: 0 }
    .form-group.selected { background: rgba(0, 0, 0, 0.1)}
    .form-group:not(:last-child) {border-bottom: 1px solid rgba(0, 0, 0, 0.1) }
    .form-control { font-size: 13px }
    .react-draggable .drag-bar { cursor: grab; margin-bottom: 0.75rem; user-select: none }
    .react-draggable-dragging .drag-bar {cursor: grabbing !important }
    .logo { margin: -15px 15px 0 0 }
    .drag-bar h3 { display: inline-block }
    .box {
        touch-action: none;
        position: fixed;
        top: 2rem;
        z-index: 999999999;
        padding: 12px;
        right: 2rem;
        overflow-y: scroll;
        width: 280px;
        color: #37352F;
        font-size: 13px;
        max-height: calc(100vh - 4rem);
        border: 1px solid rgba(0, 0, 0, 0.1);
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
`;
class App extends Component {
    constructor(props) {
        super(props)
    }
    render() {
        let editorActionId = sessionStorage.getItem('editorActionId')
        return <root.div>
            <link href="https://stackpath.bootstrapcdn.com/bootstrap/4.4.1/css/bootstrap.min.css" rel="stylesheet" crossorigin="anonymous" />
            <style>{styles}</style>
            <Draggable>
                <div className='box'>
                        <div className='drag-bar'>
                            <img className="logo" src="https://posthog.com/wp-content/uploads/elementor/thumbs/Instagram-Post-1hedgehog-off-black-ok61e8eds76dma39iqao8cwbeihgdc2a9grtrwy6p4.png" />
                            <h3>PostHog</h3><br />
                        </div>
                        <ActionEdit
                            apiURL={this.props.apiURL}
                            temporaryToken={this.props.temporaryToken}
                            actionId={(editorActionId && editorActionId != 'null') ? editorActionId : false}
                            simmer={window.simmer}
                            isEditor={true} />
                </div>
            </Draggable>
        </root.div>
    }
}

window.ph_load_editor = function(editorParams) {
    let container = document.createElement('div');
    document.body.appendChild(container);

    ReactDOM.render(<App apiURL={editorParams.apiURL} temporaryToken={editorParams.temporaryToken} />, container);
}
