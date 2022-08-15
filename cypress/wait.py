import datetime
import http.client
import time


def main():
    print("Waiting to run tests until PostHog is up and serving requests")
    booted = False
    ts = datetime.datetime.now()
    while not booted and (datetime.datetime.now() - ts).seconds < 240:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", 8000)
            conn.request("GET", "/signup")
            r = conn.getresponse()
            if r.status == 200:
                booted = True
                print("PostHog is alive! Proceeding")
                continue
            else:
                # recieved not 200 from PostHog, but service is up
                print("Found status %d" % (r.status,))
                with open("cypress/screenshots/curl.html", "wb") as f:
                    f.write(r.read)  # type: ignore
                print("PostHog is still booting. Sleeping for 1 second")
        except:
            print("PostHog is still booting. Sleeping for 1 second")
        time.sleep(1)


if __name__ == "__main__":
    main()
