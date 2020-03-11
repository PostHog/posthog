import React, { Component } from 'react'
import { toast } from 'react-toastify';

export default class InviteTeam extends Component {

    urlRef = React.createRef()
    copyToClipboard = () => {
        this.urlRef.current.focus();
        this.urlRef.current.select();
        document.execCommand('copy');
        this.urlRef.current.blur();
        toast('Link copied!');
    }
    render() {
        let url = window.location.origin == 'https://app.posthog.com' ? 'https://t.posthog.com' : window.location.origin;
        return <div>
            <br />
            Send your team the following URL:
            <br /><br />
            <div className='input-group'>
                <input type="text" ref={this.urlRef} className='form-control' value={url + "/signup/" + this.props.user.team.signup_token}/>
                <div className="input-group-append">
                    <button className='btn btn-outline-secondary' type="button" onClick={this.copyToClipboard.bind(this)}>Copy to clipboard</button>
                </div>
            </div>
            <br />
        </div>
    }
}