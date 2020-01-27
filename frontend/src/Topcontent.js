import React, { Component } from 'react'
import { NavLink } from 'react-router-dom';

export default class Topcontent extends Component {
    render() {
        return (
        	<div>
		        <div class="row right-align">
		          <div class="col-4">
		            <img class="icon-link" src="https://posthog-static-files.s3.us-east-2.amazonaws.com/Product-Assets/down-arrow-1+1.png" />Export
		          </div>
		          <div class="col-4">
		            <img class="icon-link" src="https://posthog-static-files.s3.us-east-2.amazonaws.com/Product-Assets/settings+1.png" />Settings
		          </div>
		          <div class="col-4">
		            <img class="icon-link" src="https://posthog-static-files.s3.us-east-2.amazonaws.com/Product-Assets/profile.png" />Profile
		          </div>
		        </div>
		    </div>
        )
    }
}