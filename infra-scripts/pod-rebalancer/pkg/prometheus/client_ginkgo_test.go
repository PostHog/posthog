package prometheus

import (
	"context"
	"net/http"
	"net/http/httptest"
	"time"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"

	"github.com/posthog/pod-rebalancer/pkg/logging"
)

var _ = Describe("Prometheus Client", func() {
	Describe("NewClient", func() {
		DescribeTable("should handle different endpoint configurations",
			func(endpoint string, timeout time.Duration, expectError bool) {
				logger, _ := logging.New("error")
				client, err := NewClient(endpoint, timeout, logger)

				if expectError {
					Expect(err).To(HaveOccurred())
					Expect(client).To(BeNil())
				} else {
					Expect(err).NotTo(HaveOccurred())
					Expect(client).NotTo(BeNil())
					Expect(client.timeout).To(Equal(timeout))
				}
			},
			Entry("valid endpoint and timeout", "http://localhost:9090", 30*time.Second, false),
			Entry("empty endpoint works in Prometheus client", "", 30*time.Second, false),
			Entry("invalid URL", "://invalid-url", 30*time.Second, true),
		)
	})

	Describe("Client operations", func() {
		var (
			client *Client
			server *httptest.Server
			ctx    context.Context
		)

		BeforeEach(func() {
			ctx = context.Background()
		})

		AfterEach(func() {
			if server != nil {
				server.Close()
			}
		})

		Describe("Query", func() {
			Context("with successful responses", func() {
				BeforeEach(func() {
					server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
						if r.URL.Path == "/api/v1/query" {
							w.Header().Set("Content-Type", "application/json")
							w.WriteHeader(200)
							w.Write([]byte(`{"status":"success","data":{"resultType":"vector","result":[{"metric":{"__name__":"up","instance":"localhost:9090","job":"prometheus"},"value":[1609459200,"1"]}]}}`))
						} else {
							w.WriteHeader(404)
						}
					}))

					var err error
					logger, _ := logging.New("error")
					client, err = NewClient(server.URL, 5*time.Second, logger)
					Expect(err).NotTo(HaveOccurred())
				})

				It("should successfully execute vector query", func() {
					result, err := client.Query(ctx, "up")

					Expect(err).NotTo(HaveOccurred())
					Expect(result).NotTo(BeNil())
				})
			})

			Context("with Prometheus error responses", func() {
				BeforeEach(func() {
					server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
						if r.URL.Path == "/api/v1/query" {
							w.Header().Set("Content-Type", "application/json")
							w.WriteHeader(400)
							w.Write([]byte(`{"status":"error","errorType":"bad_data","error":"parse error"}`))
						} else {
							w.WriteHeader(404)
						}
					}))

					var err error
					logger, _ := logging.New("error")
					client, err = NewClient(server.URL, 5*time.Second, logger)
					Expect(err).NotTo(HaveOccurred())
				})

				It("should return error for invalid queries", func() {
					result, err := client.Query(ctx, "invalid_query{")

					Expect(err).To(HaveOccurred())
					Expect(err.Error()).To(ContainSubstring("bad_data"))
					Expect(result).To(BeNil())
				})
			})

			Context("with HTTP errors", func() {
				BeforeEach(func() {
					server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
						if r.URL.Path == "/api/v1/query" {
							w.WriteHeader(500)
						} else {
							w.WriteHeader(404)
						}
					}))

					var err error
					logger, _ := logging.New("error")
					client, err = NewClient(server.URL, 5*time.Second, logger)
					Expect(err).NotTo(HaveOccurred())
				})

				It("should return error for HTTP failures", func() {
					result, err := client.Query(ctx, "up")

					Expect(err).To(HaveOccurred())
					Expect(err.Error()).To(ContainSubstring("prometheus query failed"))
					Expect(result).To(BeNil())
				})
			})

			Context("with timeout", func() {
				BeforeEach(func() {
					server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
						time.Sleep(200 * time.Millisecond) // Delay longer than client timeout
						w.WriteHeader(200)
						w.Write([]byte(`{"status":"success","data":{"resultType":"vector","result":[]}}`))
					}))

					var err error
					logger, _ := logging.New("error")
					client, err = NewClient(server.URL, 100*time.Millisecond, logger) // Very short timeout
					Expect(err).NotTo(HaveOccurred())
				})

				It("should timeout on slow responses", func() {
					result, err := client.Query(ctx, "up")

					Expect(err).To(HaveOccurred())
					Expect(err.Error()).To(ContainSubstring("context deadline exceeded"))
					Expect(result).To(BeNil())
				})
			})
		})

		Describe("IsHealthy", func() {
			Context("with healthy Prometheus", func() {
				BeforeEach(func() {
					server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
						w.WriteHeader(200)
						w.Write([]byte(`{"status":"success","data":{"resultType":"vector","result":[]}}`))
					}))

					var err error
					logger, _ := logging.New("error")
					client, err = NewClient(server.URL, 5*time.Second, logger)
					Expect(err).NotTo(HaveOccurred())
				})

				It("should return no error", func() {
					err := client.IsHealthy(ctx)
					Expect(err).NotTo(HaveOccurred())
				})
			})

			Context("with unhealthy Prometheus", func() {
				BeforeEach(func() {
					server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
						w.WriteHeader(500)
					}))

					var err error
					logger, _ := logging.New("error")
					client, err = NewClient(server.URL, 5*time.Second, logger)
					Expect(err).NotTo(HaveOccurred())
				})

				It("should return health check error", func() {
					err := client.IsHealthy(ctx)

					Expect(err).To(HaveOccurred())
					Expect(err.Error()).To(ContainSubstring("prometheus health check failed"))
				})
			})
		})

		Describe("QueryRange", func() {
			BeforeEach(func() {
				server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					if r.URL.Path == "/api/v1/query_range" {
						w.Header().Set("Content-Type", "application/json")
						w.WriteHeader(200)
						w.Write([]byte(`{"status":"success","data":{"resultType":"matrix","result":[]}}`))
					} else {
						w.WriteHeader(404)
					}
				}))

				var err error
				logger, _ := logging.New("error")
				client, err = NewClient(server.URL, 5*time.Second, logger)
				Expect(err).NotTo(HaveOccurred())
			})

			It("should successfully execute range query", func() {
				start := time.Now().Add(-time.Hour)
				end := time.Now()
				step := time.Minute

				result, err := client.QueryRange(ctx, "up", start, end, step)

				Expect(err).NotTo(HaveOccurred())
				Expect(result).NotTo(BeNil())
			})
		})
	})
})
