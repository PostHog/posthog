import React, { Component } from 'react'
import api from './Api';

export default class Setup extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
        }
    }
    render() {
        return (
            <div>
                <h1>Setup your PostHog account</h1>
                <label>What domain will you be using PostHog on?</label>
                <form onSubmit={(e) => {
                    event.preventDefault();
                    api.update('api/user', {team: {app_url: e.target.url.value}}).then(() => this.setState({saved: true}))
                    this.props.user.team.app_url = e.target.url.value;
                    this.props.onUpdateUser(this.props.user);

                }}>
                    <input defaultValue="https://" autoFocus style={{maxWidth: 400}} type="text" className='form-control' name='url' placeholder="https://...." />
                    <br />
                    <button className='btn btn-success' type="submit">Save url</button>
                    {this.state.saved && <p className='text-success'>URL saved</p>}

                </form>
                <br /><br />
                <h2>Integrate PostHog</h2>
                To integrate PostHog, copy + paste the following snippet to your website. Ideally, put it just above the <pre style={{display: 'inline'}}>&lt;/head&gt;</pre> tag.
                <pre className='code'>
                    {`<script>`}<br />
                    {`(function(c,a){if(!a.__SV){var b=window;try{var d,m,j,k=b.location,f=k.hash;d=function(a,b){return(m=a.match(RegExp(b+"=([^&]*)")))?m[1]:null};f&&d(f,"state")&&(j=JSON.parse(decodeURIComponent(d(f,"state"))),"mpeditor"===j.action&&(b.sessionStorage.setItem("_mpcehash",f),history.replaceState(j.desiredHash||"",c.title,k.pathname+k.search)))}catch(n){}var l,h;window.posthog=a;a._i=[];a.init=function(b,d,g){function c(b,i){var a=i.split(".");2==a.length&&(b=b[a[0]],i=a[1]);b[i]=function(){b.push([i].concat(Array.prototype.slice.call(arguments,0)))}}var e=a;"undefined"!==typeof g?e=a[g]=[]:g="posthog";e.people=e.people||[];e.toString=function(b){var a="posthog";"posthog"!==g&&(a+="."+g);b||(a+=" (stub)");return a};e.people.toString=function(){return e.toString(1)+".people (stub)"};l="disable time_event track track_pageview track_links track_forms track_with_groups add_group set_group remove_group register register_once alias unregister identify name_tag set_config reset opt_in_tracking opt_out_tracking has_opted_in_tracking has_opted_out_tracking clear_opt_in_out_tracking people.set people.set_once people.unset people.increment people.append people.union people.track_charge people.clear_charges people.delete_user people.remove".split(" ");`}
                    {`for(h=0;h<l.length;h++)c(e,l[h]);var f="set set_once union unset remove delete".split(" ");e.get_group=function(){function a(c){b[c]=function(){call2_args=arguments;call2=[c].concat(Array.prototype.slice.call(call2_args,0));e.push([d,call2])}}for(var b={},d=["get_group"].concat(Array.prototype.slice.call(arguments,0)),c=0;c<f.length;c++)a(f[c]);return b};a._i.push([b,d,g])};a.__SV=1.2;b=c.createElement("script");b.type="text/javascript";b.async=!0;b.src="file:"===c.location.protocol&&"//t.posthog.com/static/tr.js".match(/^\\/\\//)?"https://t.posthog.com/static/tr.js":"//t.posthog.com/static/tr.js";d=c.getElementsByTagName("script")[0];d.parentNode.insertBefore(b,d)}})(document,window.posthog||[]);`}
                    <br/><br />
                    {"posthog.init('" + this.props.user.team.api_token + "')"}<br />
                    {`</script>`}<br />
                </pre>
                <br /><br />
                <h2>Identifying users</h2>
                <p>To be able to link back which users made certain actions, you can pass through your own internal ID. Replace <pre style={{display: 'inline'}}>internal_id</pre> with your users' ID in your system.</p>
                <p>You only have to do this once per page.</p>
                <pre className='code'>
                    posthog.identify(internal_id);
                </pre>

                <br /><br />
                <h2>Pass user info</h2>
                <p>To be able to more easily see which user did certain actions, you can pass through properties from your user, like their email or full name.</p>
                <p>You could do this on each page load, or whenever a user updates their information (after account creation or on a profile update for example).</p>
                <pre className='code'>
                    {`posthog.people.set({`}<br />
                    {`    "email": user.email`}<br />
                    {`})`}
                </pre>
            </div>
        )
    }
}
