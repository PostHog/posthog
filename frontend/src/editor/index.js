import React, { useState } from 'react'
import ReactDOM from 'react-dom'
import root from 'react-shadow'
import { Actions } from './Actions'

import Draggable from 'react-draggable'

import Image from './move_icon.svg'


let move_icon = `<svg version="1.1" id="Capa_1" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" x="0px" y="0px" viewBox="0 0 96.6 96.6" style="enable-background:new 0 0 96.6 96.6;" xml:space="preserve"> <g> <g> <path d="M71.7,21.3c-7.2,4-12,10.6-17.9,15.9c-0.3,0.2-0.2,1.1,0,1.6c0.4,0.9,1.3,1.2,2.2,1.1c3-0.2,5.5-1.4,7.7-3.2 c5.1-4.3,10.4-8.4,14.6-13.5c0.6-0.5,1.3-1.1,1.9-1.6c3-2.7,6-5.4,8.6-8.5c-0.2,4.1-0.1,8.2,0.5,12.2c0.2,1.4,1.1,2.6,2.9,2.5 c1.6-0.1,2.8-1.1,3-2.6c0.3-2.7,0.7-5.3,0.7-8c-0.1-4.3-0.5-8.6-0.7-12.8l0,0l0,0c0.2-1.4-0.7-2.7-2-3l-0.6-0.1 C85.1-0.8,77.5,0.5,69.9,0c-0.4,0-0.9,0.7-1.1,1.1c-0.3,1,0.1,1.8,0.8,2.4c2.2,2,4.8,2.9,7.5,3.1s5.4,0.5,8.1,0.7 c-1.6,1.3-3.2,2.6-4.7,4.1C77.5,14.6,74.6,18,71.7,21.3z"/> <path d="M24.9,75.3c7.2-4,12-10.6,17.9-15.9c0.3-0.2,0.2-1.1,0-1.6c-0.4-0.9-1.3-1.2-2.2-1.1c-3,0.2-5.5,1.4-7.7,3.2 c-5.1,4.3-10.4,8.4-14.6,13.5c-0.6,0.5-1.3,1.1-1.9,1.6c-3,2.7-6,5.4-8.6,8.5c0.2-4.1,0.1-8.2-0.5-12.2c-0.2-1.4-1.1-2.6-2.9-2.5 c-1.6,0.1-2.8,1.1-3,2.6c-0.3,2.7-0.7,5.3-0.7,8c0.1,4.3,0.5,8.6,0.7,12.8l0,0l0,0c-0.2,1.4,0.7,2.7,2,3L4,95.3 c7.5,2.1,15.1,0.8,22.7,1.3c0.4,0,0.9-0.7,1.1-1.1c0.3-1-0.1-1.8-0.8-2.4c-2.2-2-4.8-2.9-7.5-3.1s-5.4-0.5-8.1-0.7 c1.6-1.3,3.2-2.6,4.7-4.1C19.1,82,22,78.6,24.9,75.3z"/> <path d="M21.3,24.9c4,7.2,10.6,12,15.9,17.9c0.2,0.3,1.1,0.2,1.6,0c0.9-0.4,1.2-1.3,1.1-2.2c-0.2-3-1.4-5.5-3.2-7.7 c-4.3-5.1-8.4-10.4-13.5-14.6c-0.5-0.6-1.1-1.3-1.6-1.9c-2.7-3-5.4-6-8.5-8.6c4.1,0.2,8.2,0.1,12.2-0.5c1.4-0.2,2.6-1.1,2.5-2.9 c-0.1-1.6-1.1-2.8-2.6-3c-2.7-0.3-5.3-0.7-8-0.7C12.9,0.8,8.6,1.2,4.4,1.4l0,0l0,0c-1.4-0.2-2.7,0.7-3,2L1.3,4 C-0.8,11.5,0.5,19.1,0,26.7c0,0.4,0.7,0.9,1.1,1.1c1,0.3,1.8-0.1,2.4-0.8c2-2.2,2.9-4.8,3.1-7.5s0.5-5.4,0.7-8.1 c1.3,1.6,2.6,3.2,4.1,4.7C14.6,19.1,18,22,21.3,24.9z"/> <path d="M75.3,71.7c-4-7.2-10.6-12-15.9-17.9c-0.2-0.3-1.1-0.2-1.6,0c-0.9,0.4-1.2,1.3-1.1,2.2c0.2,3,1.4,5.5,3.2,7.7 c4.3,5.1,8.4,10.4,13.5,14.6c0.5,0.6,1.1,1.3,1.6,1.9c2.7,3,5.4,6,8.5,8.6c-4.1-0.2-8.2-0.1-12.2,0.5c-1.4,0.2-2.6,1.1-2.5,2.9 c0.1,1.6,1.1,2.8,2.6,3c2.7,0.3,5.3,0.7,8,0.7c4.3-0.1,8.6-0.5,12.8-0.7l0,0l0,0c1.4,0.2,2.7-0.7,3-2l0.1-0.5 c2.1-7.5,0.8-15.1,1.3-22.7c0-0.4-0.7-0.9-1.1-1.1c-1-0.3-1.8,0.1-2.4,0.8c-2,2.2-2.9,4.8-3.1,7.5s-0.5,5.4-0.7,8.1 c-1.3-1.6-2.6-3.2-4.1-4.7C82,77.5,78.6,74.6,75.3,71.7z"/> </g> </g> <g> </g> <g> </g> <g> </g> <g> </g> <g> </g> <g> </g> <g> </g> <g> </g> <g> </g> <g> </g> <g> </g> <g> </g> <g> </g> <g> </g> <g> </g> </svg>`;

function getStartPosition() {
    let x = parseInt(localStorage.getItem('helperX'));
    let y = parseInt(localStorage.getItem('helperY'));
    if(!x || !y || x > window.innerWidth || y > window.innerHeight) return false;
    return {x, y};
}

function App({apiURL, temporaryToken, actionId}) {
    const [ removeHelper, setRemoveHelper ] = useState(localStorage.getItem('removeHelper'));
    window.posthog.show_helper = function() {
        setRemoveHelper(false)
    }
    if(actionId) return <Actions
        apiURL={apiURL}
        temporaryToken={temporaryToken}
        actionId={actionId}
    />
    if(removeHelper) return null;
    return <root.div>
    <style>
        {`.react-draggable {
            cursor: pointer;
            width: 50px;
            height: 50px;
            border-radius: 50%;
            box-shadow: rgba(0, 0, 0, 0.3) 0px 0px 10px;
            background: #fff;
            position: fixed;
            bottom: 25px;
            left: 25px;
            transform: ${getStartPosition()};
        }
        .react-draggable .option {
            width: 20px;
            cursor: grab;
            padding: 2px;
            height: 20px;
            border-radius: 50%;
            background: #fff;
            box-shadow: rgba(0, 0, 0, 0.2) 0px 0px 7px;
            transition: 0.5s opacity;
            position: absolute;
            opacity: 0;
        }
        .react-draggable:hover .option {
            opacity: 1;
        }
        .react-draggable .move-icon {
            margin-left: 44px;
            margin-top: -25px;
        }
        .react-draggable .move-icon::before {
            content: " ";
            background-image: url('data:image/svg+xml;utf8,${move_icon}');
            width: 14px;
            color: #333;
            position: absolute;
            height: 14px;
            margin: 3px;
         }
        .remove-helper {
            text-align: center;
            color: #dc3545;
            margin-left: 60px;
            margin-top: 4px;
            font-size: 20px;
            line-height: 18px;
        }
        .react-draggable .logo {
            background-image: url(${apiURL}/static/posthog-logo.png);
            background-size: contain;
            background-repeat: no-repeat;
            width: 36px;
            height: 40px;
            position: absolute;
            margin-top: 8px;
            margin-left: 9px;
        }

        .react-draggable-dragging {cursor: grabbing !important }`}
        </style>
        <Draggable defaultPosition={getStartPosition()} bounds="body" handle='.move-icon' onStop={(e, data) => {
            localStorage.setItem('helperX', data.x)
            localStorage.setItem('helperY', data.y)
        }}>
            <div>
            <div className='option move-icon'>
            </div>
            <div className='option remove-helper' onClick={() => {
                if(!confirm('Are you sure you want to dismiss the PostHog helper? You can always get it back by typing `posthog.showHelper()` into your console.')) return;
                setRemoveHelper(true);
                localStorage.setItem('removeHelper', 'true')
            }}>
                &times;
            </div>
                <a href={apiURL + '?source=helper'} className='logo'></a>
            </div>
        
    </Draggable>
    </root.div>
}

window.ph_load_editor = function(editorParams) {
    let container = document.createElement('div')
    document.body.appendChild(container)

    ReactDOM.render(<App
        apiURL={editorParams.apiURL}
        temporaryToken={editorParams.temporaryToken}
        actionId={editorParams.actionId}/>
    , container)
}
